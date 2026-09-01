"""Sidecar trigger API for SOC demo.

Spawns harness.py (live mode) or replay.py (replay mode) as subprocesses
when triggered by the frontend. Only one run at a time.
"""

import os
import signal
import subprocess

import httpx
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="SOC Demo Sidecar Trigger")

_state: dict = {
    "proc": None,
    "mode": None,
    "status": "idle",
}

HERE = os.path.dirname(os.path.abspath(__file__))


def _child_env() -> dict:
    env = os.environ.copy()
    env["FRONTEND_URL"] = "http://localhost:8000"
    return env


def _poll_state() -> None:
    """Update status based on subprocess poll result."""
    proc = _state["proc"]
    if proc is None:
        return
    rc = proc.poll()
    if rc is None:
        _state["status"] = "running"
    elif rc == 0:
        _state["status"] = "done"
    else:
        _state["status"] = "error"


@app.post("/trigger/replay")
async def trigger_replay(pace: float = Query(default=4.0)):
    _poll_state()
    if _state["status"] == "running":
        raise HTTPException(status_code=409, detail="A run is already in progress")

    proc = subprocess.Popen(
        [
            "python", "replay.py",
            "--server", "http://localhost:8000",
            "--pace", str(pace),
            "--scenario", "scenario.json",
        ],
        cwd=HERE,
        env=_child_env(),
    )
    _state["proc"] = proc
    _state["mode"] = "replay"
    _state["status"] = "running"
    return {"status": "running", "mode": "replay"}


@app.post("/trigger/live")
async def trigger_live():
    _poll_state()
    if _state["status"] == "running":
        raise HTTPException(status_code=409, detail="A run is already in progress")

    proc = subprocess.Popen(
        ["bash", "run-live.sh"],
        cwd=HERE,
        env=_child_env(),
    )
    _state["proc"] = proc
    _state["mode"] = "live"
    _state["status"] = "running"
    return {"status": "running", "mode": "live"}


@app.get("/status")
async def get_status():
    _poll_state()
    exit_code = None
    proc = _state["proc"]
    if proc is not None:
        exit_code = proc.returncode
    return {
        "status": _state["status"],
        "mode": _state["mode"],
        "exit_code": exit_code,
    }


@app.post("/stop")
async def stop_run():
    _poll_state()
    if _state["status"] != "running":
        raise HTTPException(status_code=409, detail="No run is in progress")

    _state["proc"].send_signal(signal.SIGTERM)
    try:
        _state["proc"].wait(timeout=10)
    except subprocess.TimeoutExpired:
        _state["proc"].kill()
        _state["proc"].wait(timeout=5)
    _state["status"] = "done"
    return {"status": "stopped"}


@app.post("/reset")
async def reset_state():
    _poll_state()
    if _state["proc"] is not None and _state["status"] == "running":
        _state["proc"].send_signal(signal.SIGTERM)
        try:
            _state["proc"].wait(timeout=5)
        except subprocess.TimeoutExpired:
            _state["proc"].kill()
    _state["proc"] = None
    _state["mode"] = None
    _state["status"] = "idle"

    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:8000/reset", timeout=5.0)
    except httpx.HTTPError:
        pass  # frontend may not be running yet

    return {"status": "idle"}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
