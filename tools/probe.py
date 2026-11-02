"""Live RE probe: find the 0x55 RFCOMM channel, activate, dump every GET reply.
Usage: python tools/probe.py [MAC] [extra hex cmd ...]   e.g. 0xC018"""
import os, struct, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import platform_bt

MAC = sys.argv[1] if len(sys.argv) > 1 and ":" in sys.argv[1] else platform_bt.paired_devices()[0][1]
EXTRA = [int(a, 16) for a in sys.argv[1:] if ":" not in a]


def crc16(b):
    c = 0xFFFF
    for x in b:
        c ^= x
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


seq = 0


def frame(cmd, payload=b""):
    global seq
    seq = (seq + 1) & 0xFF
    h = struct.pack("<BHHH", 0x55, 0x0160, cmd, len(payload)) + bytes([seq]) + payload
    return h + struct.pack("<H", crc16(h))


def frames(buf):
    out = []
    while len(buf) >= 8 and buf[0] == 0x55:
        _, ctrl, cmd, ln = struct.unpack_from("<BHHH", buf)
        tot = 8 + ln + (2 if ctrl & 0x20 else 0)
        if len(buf) < tot:
            break
        out.append((cmd | 0x8000, buf[8:8 + ln]))
        buf = buf[tot:]
    return out


def read_all(s, t=1.0):
    s.settimeout(t)
    buf = b""
    try:
        while True:
            c = s.recv(1024)
            if not c:
                break
            buf += c
    except TimeoutError:
        pass
    return buf


for ch in [15, 17, 16, 18, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]:
    try:
        s = platform_bt.open_rfcomm(MAC, ch, 6)
    except OSError as e:
        print(f"ch{ch}: {e}")
        continue
    s.send(frame(0xC001))
    r = read_all(s, 1.5)
    print(f"ch{ch}: {r.hex() or '-'}")
    if r[:1] == b"\x55":
        break
    s.close()
else:
    sys.exit("no 0x55 channel")

print(f"== using ch{ch}")
s.send(frame(0xF001))
print("activate:", read_all(s, 1).hex())
GETS = [0xC006, 0xC007, 0xC00A, 0xC00E, 0xC018, 0xC01E, 0xC01F, 0xC020, 0xC041,
        0xC042, 0xC044, 0xC04C, 0xC04E, 0xC050, 0xC029] + EXTRA
for cmd in GETS:
    s.send(frame(cmd, b"\x03" if cmd == 0xC01E else b""))
    for c, p in frames(read_all(s, 0.8)):
        print(f"0x{cmd:04X} -> 0x{c:04X} [{len(p)}] {p.hex()}  {p if cmd in (0xC006, 0xC042) else ''}")
s.close()
