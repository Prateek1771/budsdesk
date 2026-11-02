"""Live smoke test against real buds: read state, round-trip a harmless SET (low latency)."""
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("tools", 1)[0])
import buds
import platform_bt

name, mac = platform_bt.paired_devices()[0]
print("device:", name, mac)
b = buds.Buds(mac, name).start()
for _ in range(40):
    if b.state["status"] == "connected" and b.state["gestures"]:
        break
    time.sleep(0.5)
time.sleep(1.5)
print("model:", b.state["model"]["name"], b.state["model"]["base"])
print(json.dumps({k: v for k, v in b.state.items() if k not in ("gestures", "model")}))
original = b.state["latency"]
for want in (not original, original):
    b.set_latency(want)
    time.sleep(1)
    b.state["latency"] = None
    b.send(buds.GET_LATENCY)
    time.sleep(1)
    print(f"latency set {want} -> read back {b.state['latency']}")
    assert b.state["latency"] == want
b.stop()
print("ok")
