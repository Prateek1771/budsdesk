"""Nothing / CMF earbuds & headphones over Nothing's 0x55 RFCOMM protocol (all models, all OSes).

Frame (both ways): 55 | ctrl u16 LE | cmd u16 LE | len u16 LE | seq | payload | crc16-arc (if ctrl&0x20)
Host always sends ctrl=0x0160. Replies clear bit 15 of cmd; we OR it back.
Command IDs and payloads confirmed live on a CMF Buds Pro 2 (fw 1.0.1.74, see protocol.md); per-model
feature differences live in models.py, per-OS Bluetooth in platform_bt.py.
"""
import struct
import threading
import time

import models
import platform_bt

PORTS = [15, 17, 16, 18, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]  # 15 on B172

GET_VERSION, GET_INFO, GET_BATTERY, GET_WEAR = 0xC001, 0xC006, 0xC007, 0xC00A
GET_SETTINGS, GET_GESTURES, GET_ANC = 0xC00E, 0xC018, 0xC01E
GET_EQ, GET_LATENCY, GET_FIRMWARE, GET_CUSTOM_EQ, GET_BASS, GET_LISTENING = 0xC01F, 0xC041, 0xC042, 0xC044, 0xC04E, 0xC050
SET_ACTIVATE, SET_RING, SET_GESTURE, SET_SETTING = 0xF001, 0xF002, 0xF003, 0xF004
SET_ANC, SET_EQ, SET_LISTENING, SET_LATENCY, SET_CUSTOM_EQ, SET_BASS = 0xF00F, 0xF010, 0xF01D, 0xF040, 0xF041, 0xF051
EVT_BATTERY, EVT_WEAR, EVT_ANC = 0xE001, 0xE002, 0xE003

ANC = {"high": 1, "mid": 2, "low": 3, "adaptive": 4, "off": 5, "transparency": 7}
DEVICES = {2: "left", 3: "right", 4: "case", 6: "unit"}
GESTURE_TYPES = {1: "Single press", 2: "Double", 3: "Triple", 7: "Press & hold", 9: "Double press & hold",
                 10: "Rotate", 11: "Pinch both buds"}
ACTIONS = {
    1: "No action", 2: "Play / Pause", 3: "Answer call", 8: "Skip back", 9: "Skip forward",
    10: "Noise control", 11: "Voice assistant", 17: "Low lag on/off", 18: "Volume up", 19: "Volume down",
    20: "Noise control", 21: "Noise control", 22: "Noise control", 23: "Volume control", 24: "Camera shutter",
    25: "Answer / mute mic", 26: "Hang up / decline", 27: "Spatial audio", 29: "Mic mute", 31: "News",
    32: "Channel hop", 33: "Essential Space", 34: "EQ preset", 35: "Bass tuning", 36: "Treble tuning",
    37: "Voice recording",
}

# ponytail: Custom EQ template borrowed from something-x (MIT, verified on B172). Only the three
# gains change; freqs/Q are firmware-fixed. Gains at offsets 6/19/32 in order mid, treble, bass.
_EQ_TEMPLATE = bytes.fromhex(
    "0300000000010000000000007544c3f5283f020000000000c05a4500" "00803f00000000000000000c43cdcc4c3f000000000000000000"
)
_EQ_OFFSETS = (6, 19, 32)


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def encode(cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    head = struct.pack("<BHHHB", 0x55, 0x0160, cmd, len(payload), seq & 0xFF) + payload
    return head + struct.pack("<H", crc16(head))


def decode(buf: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
    """Split a byte stream into (cmd, payload) frames; returns leftover bytes."""
    out = []
    while buf:
        if buf[0] != 0x55:
            buf = buf[1:]
            continue
        if len(buf) < 8:
            break
        _, ctrl, cmd, ln = struct.unpack_from("<BHHH", buf)
        total = 8 + ln + (2 if ctrl & 0x20 else 0)
        if len(buf) < total:
            break
        # ponytail: device-side CRCs don't match (ACKs even send ffff), so RX trusts the length field
        out.append((cmd | 0x8000, bytes(buf[8 : 8 + ln])))
        buf = buf[total:]
    return out, buf


def _eq_float(v: float, preamp=False) -> bytes:
    if preamp and v >= 0:
        return b"\x00\x00\x00\x80"
    be = bytearray(struct.pack(">f", v))
    if v and be[:3] == b"\x00\x00\x00":
        be[3] |= 0x80
    return bytes(reversed(be))


def custom_eq_payload(bass: int, mid: int, treble: int) -> bytes:
    gains = [max(-6, min(6, int(g))) for g in (mid, treble, bass)]
    buf = bytearray(_EQ_TEMPLATE)
    buf[1:5] = _eq_float(-max(gains), preamp=True)
    for off, g in zip(_EQ_OFFSETS, gains):
        buf[off : off + 4] = _eq_float(float(g))
    return bytes(buf)


def parse(cmd: int, p: bytes, s: dict) -> None:
    """Fold one reply/event into state dict `s`."""
    f = s["model"]["features"]
    if cmd in (GET_BATTERY, EVT_BATTERY) and p:
        for i in range(1, 1 + p[0] * 2, 2):
            side = {2: "left", 3: "right", 4: "case", 6: "unit"}.get(p[i]) if i + 1 < len(p) else None  # 6 = headphones
            if side:
                s["battery"][side] = {"pct": p[i + 1] & 0x7F, "charging": bool(p[i + 1] & 0x80)}
    elif cmd == GET_WEAR and p:
        for i in range(1, 1 + p[0] * 2, 2):
            if i + 1 < len(p) and p[i] in (2, 3):
                side = DEVICES[p[i]]
                s["wear"][side] = bool(p[i + 1] & 0x04)
                if not p[i + 1] & 0x80:  # bud not connected -> battery unknown
                    s["battery"].pop(side, None)
    elif cmd in (GET_ANC, EVT_ANC) and len(p) >= 3:
        # [type, value, pad] triplets, optionally after a count byte; type 1 = mode
        for i in range(len(p) % 3, len(p) - 2, 3):
            if p[i] == 1:
                s["anc"] = next((k for k, v in ANC.items() if v == p[i + 1]), s["anc"])
    elif cmd == GET_GESTURES and p:
        s["gestures"] = [
            {"device": p[i], "button": p[i + 1], "type": p[i + 2], "action": p[i + 3]}
            for i in range(1, 1 + p[0] * 4, 4)
            if i + 3 < len(p)
        ]
    elif cmd == GET_SETTINGS and p:
        flags = {p[i]: p[i + 1] for i in range(1, 1 + p[0] * 2, 2) if i + 1 < len(p)}
        if 1 in flags:
            s["in_ear"] = bool(flags[1])
    elif cmd == GET_LATENCY and p:
        s["latency"] = p[0] == 1
    elif cmd == GET_BASS and len(p) >= 2:
        wire = f["bass_wire"]  # 3-stage models use [0, 5, 10], others level*2
        s["bass"] = {"on": bool(p[0]), "level": max(1, wire.index(p[1]) if wire and p[1] in wire else p[1] // 2)}
    elif cmd in (GET_LISTENING, GET_EQ) and p:
        s["listening"] = p[0]  # EQ index: listening mode or preset, per model
    elif cmd == GET_CUSTOM_EQ and len(p) >= 36:
        mid, treble, bass = (struct.unpack("<f", p[o : o + 4])[0] for o in _EQ_OFFSETS)
        s["custom_eq"] = [round(bass), round(mid), round(treble)]
    elif cmd == GET_FIRMWARE:
        s["firmware"] = p.decode(errors="replace").strip("\x00 ")
    elif cmd == GET_INFO:
        for line in p[1:].decode(errors="replace").splitlines():
            parts = line.split(",", 2)
            if len(parts) == 3 and parts[1] == "4":
                s["serial"] = parts[2]


def new_state(model=None) -> dict:
    return {
        "status": "disconnected", "battery": {}, "wear": {}, "anc": "off", "listening": 0,
        "latency": False, "in_ear": True, "bass": {"on": False, "level": 3}, "custom_eq": [0, 0, 0],
        "gestures": [], "firmware": "", "serial": "", "model": model or models.resolve(),
    }


class Buds:
    """Keeps an RFCOMM session alive in a background thread and mirrors device state."""

    def __init__(self, mac: str, name: str = "", on_change=lambda s: None):
        self.mac, self.name, self.on_change = mac, name, on_change
        self.state = new_state(models.resolve(None, name))
        self._sock = None
        self._seq = 0
        self._lock = threading.Lock()
        self._port = PORTS[0]
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._supervise, daemon=True).start()
        return self

    def _supervise(self):
        """Keep the link loop alive: an unexpected error used to kill this thread silently and leave the UI on
        "connecting" forever (v1.0.0-1.0.3). Now it is reported and the loop restarts."""
        import traceback
        while not self._stop.is_set():
            try:
                return self._run()
            except Exception:
                traceback.print_exc()
                with self._lock:
                    if self._sock:
                        self._sock.close()
                    self._sock = None
                self._set(status="unavailable")
                self._stop.wait(5)

    def stop(self):
        self._stop.set()
        if self._sock:
            self._sock.close()

    # ── public commands ────────────────────────────────────────────────
    def send(self, cmd: int, payload: bytes = b""):
        with self._lock:
            if not self._sock:
                return
            self._seq = (self._seq + 1) & 0xFF
            try:
                self._sock.send(encode(cmd, payload, self._seq))
            except OSError:
                self._sock.close()

    def set_anc(self, mode: str):
        self.send(SET_ANC, bytes([1, ANC[mode], 0]))
        self._set(anc=mode)

    @property
    def features(self):
        return self.state["model"]["features"]

    def set_listening(self, idx: int):
        """EQ: listening modes (CMF family, F01D) or classic presets (Nothing Ear family, F010)."""
        self.send(SET_LISTENING if self.features["eq"] == "listening" else SET_EQ, bytes([idx, 0]))
        self._set(listening=idx)
        if idx == self.features["custom_index"]:
            self.send(GET_CUSTOM_EQ)

    def set_custom_eq(self, bass: int, mid: int, treble: int):
        self.send(SET_CUSTOM_EQ, custom_eq_payload(bass, mid, treble))
        self._set(custom_eq=[bass, mid, treble])

    def set_latency(self, on: bool):
        self.send(SET_LATENCY, bytes([1 if on else 2, 0]))
        self._set(latency=on)

    def set_in_ear(self, on: bool):
        self.send(SET_SETTING, bytes([1, 1, int(on)]))
        self._set(in_ear=on)

    def set_bass(self, on: bool, level: int):
        wire = self.features["bass_wire"]
        level = max(1, min(self.features["bass_levels"], int(level)))
        self.send(SET_BASS, bytes([int(on), wire[level] if wire else level * 2]))
        self._set(bass={"on": on, "level": level})

    def set_gesture(self, device: int, button: int, gtype: int, action: int):
        self.send(SET_GESTURE, bytes([1, device, button, gtype, action]))
        for g in self.state["gestures"]:
            if (g["device"], g["button"], g["type"]) == (device, button, gtype):
                g["action"] = action
        self._set()

    def ring(self, which: str):
        side, on = {"both": (1, 1), "left": (2, 1), "right": (3, 1), "off": (1, 0)}[which]
        self.send(SET_RING, bytes([side, on]))

    def refresh(self):
        f = self.features
        cmds = [GET_BATTERY, GET_WEAR, GET_SETTINGS, GET_GESTURES, GET_LATENCY, GET_FIRMWARE, GET_INFO,
                GET_LISTENING if f["eq"] == "listening" else GET_EQ]
        cmds += [GET_BASS] if f["bass"] else []
        cmds += [GET_CUSTOM_EQ] if f["custom_eq"] else []
        for cmd in cmds:
            self.send(cmd)
        if f["anc"]:
            self.send(GET_ANC, b"\x03")

    def _refine_model(self):
        """The serial (GET_INFO) can pin the exact model when the Bluetooth name was ambiguous."""
        m = models.resolve(self.state["serial"], self.name)
        if m["base"] != self.state["model"]["base"] and m["base"] != "generic":
            self.state["model"] = m
            self.refresh()

    # ── session loop ───────────────────────────────────────────────────
    def _set(self, **kw):
        self.state.update(kw)
        self.on_change(self.state)

    def _connect(self) -> bool:
        for port in [self._port] + [p for p in PORTS if p != self._port]:
            try:
                s = platform_bt.open_rfcomm(self.mac, port, 6)
            except (OSError, ImportError):
                continue
            try:
                s.send(encode(GET_VERSION, b"", 0))
                if s.recv(64)[:1] == b"\x55":
                    self._sock, self._port = s, port
                    return True
            except OSError:  # TimeoutError is an OSError too
                pass
            s.close()
        return False

    def _run(self):
        while not self._stop.is_set():
            self._set(status="connecting")
            if not self._connect():
                # ponytail: busy == phone holds the socket or buds are off; retry every 5s
                self._set(status="unavailable")
                self._stop.wait(5)
                continue
            self.send(SET_ACTIVATE)
            self.refresh()
            self._set(status="connected")
            self._sock.settimeout(20)
            buf, last_poll = b"", time.monotonic()
            while not self._stop.is_set():
                try:
                    chunk = self._sock.recv(1024)
                    if not chunk:
                        break
                except TimeoutError:
                    chunk = b""
                except OSError:
                    break
                frames, buf = decode(buf + chunk)
                for cmd, p in frames:
                    if cmd == EVT_WEAR:
                        self.send(GET_WEAR)  # event carries stale data for the other bud
                    parse(cmd, p, self.state)
                    if cmd == GET_INFO:
                        self._refine_model()
                if frames:
                    self.on_change(self.state)
                if time.monotonic() - last_poll > 20:
                    last_poll = time.monotonic()
                    self.send(GET_BATTERY)
                    self.send(GET_WEAR)
            with self._lock:
                self._sock.close()
                self._sock = None
            self._set(status="disconnected")
            self._stop.wait(2)


if __name__ == "__main__":
    # Self-check against frames captured live from a B172 (fw 1.0.1.74).
    assert decode(encode(SET_GESTURE, b"\x01\x04\x01\x0a\x17", 9) + b"\x55\x60")[0] == [(SET_GESTURE, b"\x01\x04\x01\x0a\x17")]
    frames, rest = decode(bytes.fromhex("5560010140060001312e302e310a16a2" "5560010170000002ffff"))
    assert [c for c, _ in frames] == [GET_VERSION, SET_ACTIVATE] and rest == b"", frames
    s = new_state(models.resolve(None, "CMF Buds Pro 2"))
    parse(GET_BATTERY, bytes.fromhex("010264"), s)
    parse(GET_WEAR, bytes.fromhex("03028403800400"), s)
    parse(GET_ANC, bytes.fromhex("020100010700"), s)
    parse(GET_GESTURES, bytes.fromhex(
        "0f0201020902010308020107160201090103010209030103080301071603010901"
        "040101020401020104090219040103010409031a0401070104010a17"), s)
    parse(GET_SETTINGS, bytes.fromhex("0e010102000301070109010a000b000c010e010f011201150116011801"), s)
    parse(GET_BASS, bytes.fromhex("0006"), s)
    parse(GET_LATENCY, b"\x02", s)
    assert s["battery"] == {"left": {"pct": 100, "charging": False}}
    assert s["wear"] == {"left": True, "right": False}
    assert s["anc"] == "transparency", s["anc"]
    assert len(s["gestures"]) == 15 and s["gestures"][-1] == {"device": 4, "button": 1, "type": 10, "action": 23}
    assert all(f'{g["device"]}-{g["button"]}-{g["type"]}' in s["model"]["gestures"] for g in s["gestures"])
    assert s["in_ear"] and s["bass"] == {"on": False, "level": 3} and not s["latency"]
    p = custom_eq_payload(3, -2, 6)
    assert struct.unpack("<f", p[32:36])[0] == 3 and struct.unpack("<f", p[6:10])[0] == -2
    h = new_state(models.resolve(None, "Nothing Headphone (a)"))  # stereo unit + 3-stage bass
    parse(GET_BATTERY, bytes.fromhex("0106d5"), h)
    parse(GET_BASS, bytes.fromhex("010a"), h)
    assert h["battery"] == {"unit": {"pct": 85, "charging": True}} and h["bass"] == {"on": True, "level": 2}
    e = new_state(models.resolve(None, "Nothing Ear (2)"))  # classic presets
    parse(GET_EQ, b"\x02", e)
    assert e["listening"] == 2 and e["model"]["features"]["eq"] == "presets"
    print("ok")
