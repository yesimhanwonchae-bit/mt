import asyncio
import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

senders: dict = {}          # client_id -> WebSocket
viewers: dict = {}          # viewer WebSocket -> set of subscribed client_ids
sender_last_frame: dict = {}  # client_id -> latest jpeg bytes (thumbnail용)

async def broadcast_pc_list():
    msg = json.dumps({"type": "pc_list", "ids": list(senders.keys())})
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
.card.offline{opacity:.4;border-color:#555}
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
  <div id="modal-wrap"><img id="modal-img"></div>
</div>
<script>
var cards={}, lastSeen={}, focused=null, pcCount=0, ws=null;

setInterval(function(){
  var now=Date.now();
  Object.keys(lastSeen).forEach(function(id){
    var card=document.getElementById('card_'+id);
    if(!card) return;
    card.classList.toggle('offline', now-lastSeen[id]>8000);
  });
},1000);

function timeStr(){
  var d=new Date();
  return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0')+':'+d.getSeconds().toString().padStart(2,'0');
}

function groupKey(id){ return id.replace(/_\\d+$/,''); }
function insertCard(el,id){
  var grid=document.getElementById('grid');
  var gk=groupKey(id);
  var siblings=Array.from(grid.children).filter(function(c){return groupKey(c.dataset.id||'')===gk;});
  if(siblings.length>0) siblings[siblings.length-1].after(el);
  else grid.appendChild(el);
}

function addCard(id){
  if(cards[id]) return;
  pcCount++;
  document.getElementById('pc-count').textContent='PC '+pcCount+'대';
  var d=document.createElement('div');
  d.className='card';d.id='card_'+id;d.dataset.id=id;
  d.innerHTML='<div class="card-header"><span class="card-name">'+id+'</span><span class="card-dot"></span></div>'
             +'<div class="card-hint">클릭해서 보기</div>';
  d.onclick=function(){ openModal(id); };
  insertCard(d,id);
  cards[id]=true;
  lastSeen[id]=Date.now();
}

function removeCard(id){
  var el=document.getElementById('card_'+id);
  if(el){ el.remove(); pcCount--; document.getElementById('pc-count').textContent='PC '+pcCount+'대'; }
  delete cards[id];
  delete lastSeen[id];
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
        msg.ids.forEach(function(id){ addCard(id); });
      } else if(msg.type==='pc_join'){
        addCard(msg.id);
      } else if(msg.type==='pc_leave'){
        removeCard(msg.id);
      }
      return;
    }
    var buf=new Uint8Array(e.data);
    var sep=buf.indexOf(0x7C);
    if(sep<0) return;
    var id=new TextDecoder().decode(buf.slice(0,sep));
    var jpeg=buf.slice(sep+1);
    lastSeen[id]=Date.now();
    if(focused===id){
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
    await broadcast_pc_list()
    # join 알림
    join_msg = json.dumps({"type": "pc_join", "id": client_id})
    for v in list(viewers):
        try:
            await v.send_text(join_msg)
        except Exception:
            pass
    try:
        while True:
            frame = await ws.receive_bytes()
            sender_last_frame[client_id] = frame
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
    except (WebSocketDisconnect, Exception):
        senders.pop(client_id, None)
        sender_last_frame.pop(client_id, None)
        leave_msg = json.dumps({"type": "pc_leave", "id": client_id})
        for v in list(viewers):
            try:
                await v.send_text(leave_msg)
            except Exception:
                pass


@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    await ws.accept()
    viewers[ws] = set()
    # 현재 연결된 PC 목록 전송
    try:
        await ws.send_text(json.dumps({"type": "pc_list", "ids": list(senders.keys())}))
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
                    # 최신 프레임 즉시 전송 (첫 화면 빠르게)
                    if pid in sender_last_frame and sender_last_frame[pid]:
                        header = (pid + "|").encode("utf-8")
                        try:
                            await ws.send_bytes(header + sender_last_frame[pid])
                        except Exception:
                            pass
                elif data.get("type") == "unsub":
                    viewers[ws].discard(data.get("id", ""))
            except asyncio.TimeoutError:
                try:
                    await ws.send_text("ping")
                except Exception:
                    break
    except (WebSocketDisconnect, Exception):
        pass
    viewers.pop(ws, None)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
