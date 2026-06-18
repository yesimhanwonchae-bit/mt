import asyncio
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

senders: dict = {}   # client_id -> WebSocket
viewers: set = set() # viewer WebSockets

VIEWER_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Why So Serious</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#111;color:#eee;font-family:sans-serif;min-height:100vh;display:flex;flex-direction:column}
header{background:#1e2538;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}
h1{font-size:15px;color:#00c8f0}
#info{font-size:12px;color:#94a3b8;margin-left:auto;display:flex;gap:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:8px;padding:8px;flex:1}
.group{display:contents}
.card{background:#1a1a2e;border:1px solid #333;border-radius:6px;overflow:hidden;cursor:pointer;transition:border-color .2s,opacity .3s}
.card:hover{border-color:#00c8f0}
.card.offline{opacity:.4;border-color:#555}
.card-header{background:#1e2538;padding:6px 10px;font-size:12px;color:#94a3b8;display:flex;justify-content:space-between;align-items:center}
.card-name{font-weight:bold;color:#cdd}
.card-time{font-size:10px;color:#556}
.card-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;flex-shrink:0;margin-left:6px}
.card.offline .card-dot{background:#555}
.card-img-wrap{position:relative;width:100%;overflow:hidden;line-height:0}
.card-img-wrap img{width:100%;display:block;position:absolute;top:0;left:0;image-rendering:auto;image-rendering:-webkit-optimize-contrast}
.card-img-wrap img.active{position:relative}
#modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.95);z-index:999;flex-direction:column}
#modal.open{display:flex}
#modal-header{background:#1e2538;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}
#modal-title{font-size:14px;color:#00c8f0}
#modal-hint{font-size:11px;color:#556;margin-left:8px}
#modal-close{margin-left:auto;background:#444;color:#eee;border:none;padding:4px 14px;border-radius:4px;cursor:pointer;font-size:13px}
#modal-wrap{flex:1;overflow:hidden;position:relative;cursor:grab;touch-action:none}
#modal-wrap.dragging{cursor:grabbing}
#modal-img{position:absolute;top:0;left:0;transform-origin:top left;image-rendering:auto;max-width:none;will-change:transform}
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
var cards={}, lastSeen={}, focused=null, pcCount=0;
// cards[id] = {a, b, cur} — 더블버퍼링 img로 번쩍임 제거

// ── 오프라인 감지
setInterval(function(){
  var now=Date.now();
  Object.keys(lastSeen).forEach(function(id){
    var card=document.getElementById('card_'+id);
    if(!card) return;
    card.classList.toggle('offline', now-lastSeen[id]>5000);
  });
},1000);

function timeStr(){
  var d=new Date();
  return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0')+':'+d.getSeconds().toString().padStart(2,'0');
}

function groupKey(id){ return id.replace(/_\d+$/,''); }
function insertCard(el,id){
  var grid=document.getElementById('grid');
  var gk=groupKey(id);
  var siblings=Array.from(grid.children).filter(function(c){return groupKey(c.dataset.id||'')===gk;});
  if(siblings.length>0) siblings[siblings.length-1].after(el);
  else grid.appendChild(el);
}

// ── 모달
var mScale=1,mTx=0,mTy=0,mDrag=false,mOx,mOy,pinchDist=0;
var mImg=document.getElementById('modal-img');
var mBack=new Image(); // 백버퍼
var mFirstFrame=true;

function fitModal(){
  var wrap=document.getElementById('modal-wrap');
  var ww=wrap.clientWidth,wh=wrap.clientHeight;
  var iw=mImg.naturalWidth||ww,ih=mImg.naturalHeight||wh;
  mScale=Math.min(ww/iw,wh/ih);mTx=0;mTy=0;applyModal();
}
function applyModal(){
  mImg.style.transform='translate('+mTx+'px,'+mTy+'px) scale('+mScale+')';
  mImg.style.imageRendering=mScale>=1?'pixelated':'auto';
}
function openModal(id){
  focused=id;mScale=1;mTx=0;mTy=0;mFirstFrame=true;
  document.getElementById('modal-title').textContent=id;
  document.getElementById('modal').classList.add('open');
}
function closeModal(){
  focused=null;
  document.getElementById('modal').classList.remove('open');
  mImg.src=''; mBack.src='';
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

// ── 더블버퍼링 img 업데이트
function updateCard(jpeg, card){
  var url=URL.createObjectURL(new Blob([jpeg],{type:'image/jpeg'}));
  card.back.onload=function(){
    var oldUrl=card.front._url;
    card.front.src=card.back.src;
    card.front._url=card.back.src;
    card.back.src='';
    if(oldUrl) URL.revokeObjectURL(oldUrl);
  };
  card.back.src=url;
}

// ── WebSocket
function connect(){
  var proto=location.protocol==='https:'?'wss:':'ws:';
  var ws=new WebSocket(proto+'//'+location.host+'/ws/viewer');
  ws.binaryType='arraybuffer';
  ws.onopen=function(){document.getElementById('ws-status').textContent='연결됨';};
  ws.onmessage=function(e){
    if(typeof e.data==='string') return;
    var buf=new Uint8Array(e.data);
    var sep=buf.indexOf(0x7C);
    if(sep<0) return;
    var id=new TextDecoder().decode(buf.slice(0,sep));
    var jpeg=buf.slice(sep+1);
    lastSeen[id]=Date.now();
    if(!cards[id]){
      pcCount++;
      document.getElementById('pc-count').textContent='PC '+pcCount+'대';
      var d=document.createElement('div');
      d.className='card';d.id='card_'+id;d.dataset.id=id;
      d.onclick=function(){openModal(id);};
      var wrap=document.createElement('div');wrap.className='card-img-wrap';
      var imgA=new Image();imgA.className='active';
      var imgB=new Image();
      wrap.appendChild(imgA);
      d.innerHTML='<div class="card-header"><span class="card-name">'+id+'</span><span class="card-time">--:--:--</span><span class="card-dot"></span></div>';
      d.appendChild(wrap);
      insertCard(d,id);
      cards[id]={front:imgA, back:imgB};
    }
    var th=document.querySelector('#card_'+id+' .card-time');
    if(th) th.textContent=timeStr();
    updateCard(jpeg, cards[id]);
    if(focused===id){
      var url2=URL.createObjectURL(new Blob([jpeg],{type:'image/jpeg'}));
      mBack.onload=function(){
        var oldUrl=mImg._url;
        mImg.src=mBack.src; mImg._url=mBack.src;
        mBack.src='';
        if(oldUrl) URL.revokeObjectURL(oldUrl);
        if(mFirstFrame){mFirstFrame=false;fitModal();}
      };
      mBack.src=url2;
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
    try:
        while True:
            frame = await ws.receive_bytes()
            header = (client_id + "|").encode("utf-8")
            payload = header + frame
            dead = []
            for v in list(viewers):
                try:
                    await v.send_bytes(payload)
                except Exception:
                    dead.append(v)
            for d in dead:
                viewers.discard(d)
    except (WebSocketDisconnect, Exception):
        senders.pop(client_id, None)


@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    await ws.accept()
    viewers.add(ws)
    try:
        while True:
            await asyncio.sleep(20)
            try:
                await ws.send_text("ping")
            except Exception:
                break
    except (WebSocketDisconnect, Exception):
        pass
    viewers.discard(ws)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
