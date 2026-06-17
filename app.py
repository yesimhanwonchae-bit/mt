import asyncio
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()

senders: dict = {}   # client_id -> WebSocket
viewers: set = set() # viewer WebSockets

VIEWER_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Why So Serious</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#111;color:#eee;font-family:sans-serif;min-height:100vh}
header{background:#1e2538;padding:10px 16px;display:flex;align-items:center;gap:12px}
h1{font-size:15px;color:#00c8f0}
#status{font-size:12px;color:#94a3b8;margin-left:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:8px;padding:8px}
.card{background:#1a1a2e;border:1px solid #333;border-radius:6px;overflow:hidden;cursor:pointer}
.card:hover{border-color:#00c8f0}
.card-header{background:#1e2538;padding:6px 10px;font-size:12px;color:#94a3b8}
.card img{width:100%;display:block}
#modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.92);z-index:999;flex-direction:column}
#modal.open{display:flex}
#modal-header{background:#1e2538;padding:10px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}
#modal-title{font-size:14px;color:#00c8f0}
#modal-close{margin-left:auto;background:#444;color:#eee;border:none;padding:4px 14px;border-radius:4px;cursor:pointer;font-size:13px}
#modal-wrap{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;padding:8px}
#modal-img{max-width:100%;max-height:100%;object-fit:contain}
</style></head><body>
<header><h1>Posmos CS 전체 모니터</h1><span id="status">연결 중...</span></header>
<div class="grid" id="grid"></div>
<div id="modal">
  <div id="modal-header">
    <span id="modal-title"></span>
    <button id="modal-close" onclick="closeModal()">닫기 ✕</button>
  </div>
  <div id="modal-wrap"><img id="modal-img"></div>
</div>
<script>
var cards = {};
var focused = null;

function openModal(clientId) {
  focused = clientId;
  document.getElementById('modal-title').textContent = clientId;
  document.getElementById('modal').classList.add('open');
}
function closeModal() {
  focused = null;
  document.getElementById('modal').classList.remove('open');
  document.getElementById('modal-img').src = '';
}
document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeModal(); });

function connect() {
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto + '//' + location.host + '/ws/viewer');
  ws.binaryType = 'arraybuffer';
  ws.onopen = function() { document.getElementById('status').textContent = '연결됨'; };
  ws.onmessage = function(e) {
    if (typeof e.data === 'string') return;
    var buf = new Uint8Array(e.data);
    var sep = buf.indexOf(0x7C);
    if (sep < 0) return;
    var clientId = new TextDecoder().decode(buf.slice(0, sep));
    var jpeg = buf.slice(sep + 1);
    var blob = new Blob([jpeg], {type:'image/jpeg'});
    var url = URL.createObjectURL(blob);
    if (!cards[clientId]) {
      var d = document.createElement('div');
      d.className = 'card';
      d.id = 'card_' + clientId;
      d.onclick = function(){ openModal(clientId); };
      d.innerHTML = '<div class="card-header">' + clientId + '</div><img id="img_' + clientId + '">';
      document.getElementById('grid').appendChild(d);
      cards[clientId] = document.getElementById('img_' + clientId);
    }
    var img = cards[clientId];
    if (img._prev) URL.revokeObjectURL(img._prev);
    img._prev = url;
    img.src = url;
    if (focused === clientId) {
      var mimg = document.getElementById('modal-img');
      var blob2 = new Blob([jpeg], {type:'image/jpeg'});
      var url2 = URL.createObjectURL(blob2);
      if (mimg._prev) URL.revokeObjectURL(mimg._prev);
      mimg._prev = url2;
      mimg.src = url2;
    }
  };
  ws.onclose = function() {
    document.getElementById('status').textContent = '연결 끊김 — 재연결 중...';
    setTimeout(connect, 3000);
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
