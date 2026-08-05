"""MemoryHub SOC demo — event relay + static server.

Viewers connect on /ws and receive every event pushed to POST /emit.
The harness (or replay.py) is the producer; this server is a dumb pipe.

Run:  uvicorn server:app --port 8000
Set EMIT_TOKEN to require an X-Emit-Token header on POST /emit
(recommended when exposed on a public OpenShift route).
"""
import json
import os
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

app = FastAPI()
EMIT_TOKEN = os.environ.get("EMIT_TOKEN", "")
viewers: set[WebSocket] = set()
history: list[dict] = []  # replayed to late-joining viewers


@app.websocket("/ws")
async def ws_viewer(ws: WebSocket):
    await ws.accept()
    for e in history:  # catch up
        await ws.send_text(json.dumps(e))
    viewers.add(ws)
    try:
        while True:
            await ws.receive_text()  # ignore client chatter / keepalives
    except WebSocketDisconnect:
        viewers.discard(ws)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "viewers": len(viewers), "history": len(history)}


def check_token(token):
    if EMIT_TOKEN and token != EMIT_TOKEN:
        raise HTTPException(status_code=403, detail="bad or missing X-Emit-Token")


@app.post("/emit")
async def emit(event: dict, x_emit_token: str | None = Header(default=None)):
    check_token(x_emit_token)
    history.append(event)
    dead = []
    for v in viewers:
        try:
            await v.send_text(json.dumps(event))
        except Exception:
            dead.append(v)
    for d in dead:
        viewers.discard(d)
    return {"viewers": len(viewers), "history": len(history)}


@app.post("/reset")
async def reset(x_emit_token: str | None = Header(default=None)):
    check_token(x_emit_token)
    history.clear()
    return {"ok": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
