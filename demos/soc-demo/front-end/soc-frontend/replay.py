"""Stand-in for harness.py — replays scenario.json into the relay server.

Auto-play (recording mode):   python replay.py --pace 4
Click-through (live mode):    python replay.py --pace 0
    (all events buffer instantly; the presenter steps through them
     in the frontend with SPACE / arrow keys)

Stdlib only, no dependencies.
"""
import argparse, json, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://localhost:8000")
ap.add_argument("--pace", type=float, default=4.0, help="seconds between events; 0 = burst")
ap.add_argument("--scenario", default="scenario.json")
ap.add_argument("--token", default="", help="X-Emit-Token if the server sets EMIT_TOKEN")
args = ap.parse_args()


def post(path, body):
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["X-Emit-Token"] = args.token
    req = urllib.request.Request(args.server + path, json.dumps(body).encode(), headers)
    return urllib.request.urlopen(req)


post("/reset", {})
with open(args.scenario, encoding="utf-8") as f:
    events = json.load(f)
for e in events:
    post("/emit", e)
    print(f"[{e.get('timestamp','--:--')}] {e['type']:<15} {e.get('agent','')}")
    if args.pace:
        time.sleep(args.pace)
print(f"done — {len(events)} events sent")
