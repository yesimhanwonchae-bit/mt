import asyncio
import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

senders: dict = {}              # client_id -> WebSocket
viewers: dict = {}              # viewer WebSocket -> set of subscribed client_ids
sender_last_frame: dict = {}    # client_id -> latest jpeg bytes
known_pcs: dict = {}            # client_id -> {"online": bool}
global_wanted: set = set()      # union of all viewer subscriptions

def update_global_wanted():
    global_wanted.clear()
    for subs in viewers.values():
        global_wanted.update(subs)

async def notify_viewers_text(msg: str):
    for v in list(viewers):
        try:
            await v.send_text(msg)
        except Exception:
            pass

VIEWER_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Why So Serious</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#111;color:#eee;font-family:sans-serif;min-height:100vh;display:flex;flex-direction:column}
header{background:#1e2538;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}
h1{font-size:15px;color:#00c8f0}
#info{font-size:12px;color:#94a3b8;margin-left:auto;display:flex;gap:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;padding:8px;flex:1}
.card{background:#1a1a2e;border:1px solid #333;border-radius:6px;overflow:hidden;cursor:pointer;transition:border-color .2s,opacity .3s}
.card:hover{border-color:#00c8f0}
.card.offline{opacity:.4;cursor:default}
.card-header{background:#1e2538;padding:10px 14px;font-size:13px;color:#cdd;display:flex;justify-content:space-between;align-items:center}
.card-name{font-weight:bold}
.card-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;flex-shrink:0;margin-left:6px}
.card.offline .card-dot{background:#555}
.card-hint{font-size:11px;color:#556;padding:18px;text-align:center}
#modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.95);z-index:999;flex-direction:column}
#modal.open{display:flex}
#modal-header{background:#1e2538;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}
#modal-title{font-size:14px;color:#00c8f0}
#modal-hint{font-size:11px;color:#556;margin-left:8px}
#modal-close{margin-left:auto;background:#444;color:#eee;border:none;padding:4px 14px;border-radius:4px;cursor:pointer;font-size:13px}
#modal-wrap{flex:1;overflow:hidden;position:relative;cursor:grab;touch-action:none}
#modal-wrap.dragging{cursor:grabbing}
#modal-img{position:absolute;max-width:none;max-height:none}
#modal-loading{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#94a3b8;font-size:13px}
</style></head><body>
<header>
  <h1>Why So Serious</h1>
  <div id="info"><span id="pc-count">PC 0대</span><span id="ws-status">연결 중...</span></div>
</header>
<div class="grid" id="grid"></div>
<div id="modal">
  <div id="modal-header">
    <span id="modal-title"></span>
    <span id="modal-hint">휠: 확대 | 드래그: 이동 | 더블탭: 초기화 | ESC: 닫기</span>
    <button id="modal-close" onclick="closeModal()">닫기 ✕</button>
  </div>
  <div id="modal-wrap">
    <div id="modal-loading">연결 중...</div>
    <img id="modal-img">
  </div>
</div>
<script>
var cards={}, focused=null, pcCount=0, ws=null;

function groupKey(id){ return id.replace(/_\\d+$/,''); }
function insertCard(el,id){
  var grid=document.getElementById('grid');
  var gk=groupKey(id);
  var siblings=Array.from(grid.children).filter(function(c){return groupKey(c.dataset.id||'')===gk;});
  if(siblings.length>0) siblings[siblings.length-1].after(el);
  else grid.appendChild(el);
}

function addCard(id, online){
  if(cards[id]){
    setOnline(id, online);
    return;
  }
  pcCount++;
  document.getElementById('pc-count').textContent='PC '+pcCount+'대';
  var d=document.createElement('div');
  d.className='card'+(online?'':' offline');
  d.id='card_'+id; d.dataset.id=id;
  d.innerHTML='<div class="card-header"><span class="card-name">'+id+'</span><span class="card-dot"></span></div>'
             +'<div class="card-hint">'+(online?'클릭해서 보기':'오프라인')+'</div>';
  d.onclick=function(){
    if(d.classList.contains('offline')) return;
    openModal(id);
  };
  insertCard(d,id);
  cards[id]=true;
}

function setOnline(id, online){
  var el=document.getElementById('card_'+id);
  if(!el) return;
  el.classList.toggle('offline',!online);
  var hint=el.querySelector('.card-hint');
  if(hint) hint.textContent=online?'클릭해서 보기':'오프라인';
}

// ── 모달
var mScale=1,mTx=0,mTy=0,mDrag=false,mOx,mOy,pinchDist=0;
var mImg=document.getElementById('modal-img');
var mFirstFrame=true;

function fitModal(){
  var wrap=document.getElementById('modal-wrap');
  var ww=wrap.clientWidth,wh=wrap.clientHeight;
  var iw=mImg.naturalWidth||ww,ih=mImg.naturalHeight||wh;
  mScale=Math.min(ww/iw,wh/ih);
  mTx=(ww-iw*mScale)/2; mTy=(wh-ih*mScale)/2;
  applyModal();
}
function applyModal(){
  var iw=mImg.naturalWidth,ih=mImg.naturalHeight;
  if(!iw||!ih) return;
  mImg.style.width=iw*mScale+'px'; mImg.style.height=ih*mScale+'px';
  mImg.style.left=mTx+'px'; mImg.style.top=mTy+'px';
}
function openModal(id){
  focused=id; mScale=1; mTx=0; mTy=0; mFirstFrame=true;
  mImg.src=''; mImg.style.width=''; mImg.style.height='';
  document.getElementById('modal-loading').style.display='block';
  document.getElementById('modal-title').textContent=id;
  document.getElementById('modal').classList.add('open');
  if(ws && ws.readyState===1) ws.send(JSON.stringify({type:'sub',id:id}));
}
function closeModal(){
  if(focused && ws && ws.readyState===1) ws.send(JSON.stringify({type:'unsub',id:focused}));
  focused=null;
  document.getElementById('modal').classList.remove('open');
  mImg.src='';
}

var mw=document.getElementById('modal-wrap');
mw.addEventListener('wheel',function(e){
  e.preventDefault();
  var r=mw.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  var d=e.deltaY<0?1.15:1/1.15;
  mTx=mx-(mx-mTx)*d;mTy=my-(my-mTy)*d;mScale*=d;
  if(mScale<0.05)mScale=0.05;if(mScale>30)mScale=30;applyModal();
},{passive:false});
mw.addEventListener('mousedown',function(e){mDrag=true;mOx=e.clientX-mTx;mOy=e.clientY-mTy;mw.classList.add('dragging');});
document.addEventListener('mousemove',function(e){if(!mDrag)return;mTx=e.clientX-mOx;mTy=e.clientY-mOy;applyModal();});
document.addEventListener('mouseup',function(){mDrag=false;mw.classList.remove('dragging');});
mw.addEventListener('dblclick',function(){fitModal();});
mw.addEventListener('touchstart',function(e){
  if(e.touches.length===1){mDrag=true;mOx=e.touches[0].clientX-mTx;mOy=e.touches[0].clientY-mTy;}
  if(e.touches.length===2){mDrag=false;pinchDist=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);}
  e.preventDefault();
},{passive:false});
mw.addEventListener('touchmove',function(e){
  e.preventDefault();
  if(e.touches.length===1&&mDrag){mTx=e.touches[0].clientX-mOx;mTy=e.touches[0].clientY-mOy;applyModal();}
  if(e.touches.length===2){
    var nd=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
    var cx=(e.touches[0].clientX+e.touches[1].clientX)/2,cy=(e.touches[0].clientY+e.touches[1].clientY)/2;
    var r=mw.getBoundingClientRect(),mx=cx-r.left,my=cy-r.top;
    var d=nd/pinchDist;pinchDist=nd;
    mTx=mx-(mx-mTx)*d;mTy=my-(my-mTy)*d;mScale*=d;
    if(mScale<0.05)mScale=0.05;if(mScale>30)mScale=30;applyModal();
  }
},{passive:false});
mw.addEventListener('touchend',function(e){if(e.touches.length===0)mDrag=false;},{passive:false});
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});

function updateImg(img,jpeg,onFirst){
  var blob=new Blob([jpeg],{type:'image/jpeg'});
  var url=URL.createObjectURL(blob);
  var oldUrl=img._url||null;
  img.onload=function(){ if(oldUrl) URL.revokeObjectURL(oldUrl); if(onFirst) onFirst(); };
  img._url=url; img.src=url;
}

function connect(){
  var proto=location.protocol==='https:'?'wss:':'ws:';
  ws=new WebSocket(proto+'//'+location.host+'/ws/viewer');
  ws.binaryType='arraybuffer';
  ws.onopen=function(){ document.getElementById('ws-status').textContent='연결됨'; };
  ws.onmessage=function(e){
    if(typeof e.data==='string'){
      var msg=JSON.parse(e.data);
      if(msg.type==='pc_list'){
        msg.pcs.forEach(function(p){ addCard(p.id, p.online); });
      } else if(msg.type==='pc_status'){
        if(!cards[msg.id]) addCard(msg.id, msg.online);
        else setOnline(msg.id, msg.online);
      }
      return;
    }
    var buf=new Uint8Array(e.data);
    var sep=buf.indexOf(0x7C);
    if(sep<0) return;
    var id=new TextDecoder().decode(buf.slice(0,sep));
    var jpeg=buf.slice(sep+1);
    if(focused===id){
      document.getElementById('modal-loading').style.display='none';
      var isFirst=mFirstFrame;
      if(isFirst) mFirstFrame=false;
      updateImg(mImg,jpeg,isFirst?fitModal:null);
    }
  };
  ws.onclose=function(){
    document.getElementById('ws-status').textContent='연결 끊김 — 재연결 중...';
    setTimeout(connect,3000);
  };
}
connect();
</script></body></html>"""


@app.get("/")
async def root():
    return HTMLResponse(VIEWER_HTML)


@app.websocket("/ws/sender/{client_id}")
async def ws_sender(ws: WebSocket, client_id: str):
    await ws.accept()
    senders[client_id] = ws
    sender_last_frame[client_id] = b""
    known_pcs[client_id] = {"online": True}
    await notify_viewers_text(json.dumps({"type": "pc_status", "id": client_id, "online": True}))
    try:
        while True:
            frame = await ws.receive_bytes()
            sender_last_frame[client_id] = frame

            if client_id not in global_wanted:
                # 아무도 안 보고 있으면 연결 끊기
                break

            header = (client_id + "|").encode("utf-8")
            payload = header + frame
            dead = []
            for v, subs in list(viewers.items()):
                if client_id in subs:
                    try:
                        await v.send_bytes(payload)
                    except Exception:
                        dead.append(v)
            for d in dead:
                viewers.pop(d, None)
                update_global_wanted()
    except (WebSocketDisconnect, Exception):
        pass

    senders.pop(client_id, None)
    if client_id in known_pcs:
        known_pcs[client_id]["online"] = False
    await notify_viewers_text(json.dumps({"type": "pc_status", "id": client_id, "online": False}))


@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    await ws.accept()
    viewers[ws] = set()
    try:
        await ws.send_text(json.dumps({
            "type": "pc_list",
            "pcs": [{"id": k, "online": v["online"]} for k, v in known_pcs.items()]
        }))
    except Exception:
        pass
    try:
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=20)
                data = json.loads(msg)
                if data.get("type") == "sub":
                    pid = data.get("id", "")
                    viewers[ws].add(pid)
                    update_global_wanted()
                    # 최신 프레임 즉시 전송
                    if pid in sender_last_frame and sender_last_frame[pid]:
                        header = (pid + "|").encode("utf-8")
                        try:
                            await ws.send_bytes(header + sender_last_frame[pid])
                        except Exception:
                            pass
                elif data.get("type") == "unsub":
                    pid = data.get("id", "")
                    viewers[ws].discard(pid)
                    update_global_wanted()
                    # 아무도 안 보면 sender 연결 끊기
                    if pid not in global_wanted and pid in senders:
                        try:
                            await senders[pid].close()
                        except Exception:
                            pass
            except asyncio.TimeoutError:
                try:
                    await ws.send_text("ping")
                except Exception:
                    break
    except (WebSocketDisconnect, Exception):
        pass

    viewers.pop(ws, None)
    update_global_wanted()
    # 이 뷰어가 보던 PC 중 아무도 안 보는 것들 연결 끊기
    for pid in list(senders.keys()):
        if pid not in global_wanted:
            try:
                await senders[pid].close()
            except Exception:
                pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
