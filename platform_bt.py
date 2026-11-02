"""Per-OS classic-Bluetooth plumbing: list paired Nothing/CMF devices and open an RFCOMM link.

Windows + Linux: stdlib socket.AF_BLUETOOTH (WinSock / BlueZ).
macOS: Python has no AF_BLUETOOTH, so this uses IOBluetooth through PyObjC
(pip install pyobjc-framework-IOBluetooth).
Every connection exposes the same tiny interface: send(bytes), recv(n) -> bytes
(b"" = closed, raises TimeoutError on timeout), settimeout(s), close().
"""
import re
import socket
import subprocess
import sys

from models import NOTHING_NAME

MAC = re.compile(r"([0-9A-F]{2}(?:[:-][0-9A-F]{2}){5})", re.I)


# ── paired devices ──────────────────────────────────────────────────────
def parse_pnp(out: str):
    """Windows `Get-PnpDevice` lines 'Name|BTHENUM\\DEV_XXXXXXXXXXXX\\...'."""
    found = []
    for line in out.splitlines():
        name, _, inst = line.partition("|")
        m = re.search(r"DEV_([0-9A-F]{12})", inst, re.I)
        if m and NOTHING_NAME.search(name):
            found.append((name.strip(), ":".join(m[1][i:i + 2] for i in range(0, 12, 2)).upper()))
    return found


def parse_bluetoothctl(out: str):
    """BlueZ `bluetoothctl devices Paired` lines 'Device AA:BB:CC:DD:EE:FF Name'."""
    found = []
    for line in out.splitlines():
        m = re.match(r"\s*Device\s+([0-9A-F:]{17})\s+(.+)", line, re.I)
        if m and NOTHING_NAME.search(m[2]):
            found.append((m[2].strip(), m[1].upper()))
    return found


def _run(cmd):
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console flash on Windows
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, **kw).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def paired_devices():
    """[(name, 'AA:BB:CC:DD:EE:FF')] for paired Nothing/CMF audio devices, deduplicated."""
    if sys.platform == "win32":
        found = parse_pnp(_run(["powershell", "-NoProfile", "-Command",
                                "Get-PnpDevice -Class Bluetooth | ? InstanceId -like 'BTHENUM\\DEV_*' | % { $_.FriendlyName + '|' + $_.InstanceId }"]))
    elif sys.platform == "darwin":
        found = _mac_paired()
    else:
        out = _run(["bluetoothctl", "devices", "Paired"])
        if "Device" not in out:  # BlueZ < 5.65
            out = _run(["bluetoothctl", "paired-devices"])
        found = parse_bluetoothctl(out)
    seen, uniq = set(), []
    for name, mac in found:
        if mac not in seen:
            seen.add(mac); uniq.append((name, mac))
    return uniq


# ── RFCOMM ──────────────────────────────────────────────────────────────
class _Sock(socket.socket):
    """send() always sends the whole frame, like the macOS channel (socket attributes are read-only,
    so this has to be a subclass; assigning s.send = s.sendall raises AttributeError)."""

    def send(self, data, *flags):
        self.sendall(data, *flags)
        return len(data)


def open_rfcomm(mac: str, channel: int, timeout: float = 6):
    if sys.platform == "darwin":
        return _MacRFCOMM(mac, channel, timeout)
    s = _Sock(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(timeout)
    try:
        s.connect((mac, channel))
    except OSError:
        s.close()
        raise
    return s


# ── macOS (IOBluetooth via PyObjC) ──────────────────────────────────────
def _mac_paired():
    try:
        from IOBluetooth import IOBluetoothDevice
    except ImportError:
        return []
    out = []
    for d in IOBluetoothDevice.pairedDevices() or []:
        name, addr = str(d.name() or ""), str(d.addressString() or "")
        if NOTHING_NAME.search(name) and MAC.match(addr):
            out.append((name, addr.replace("-", ":").upper()))
    return out


class _MacRFCOMM:
    """IOBluetooth delivers data to a delegate on the run loop of the thread that opened the
    channel, so recv() pumps that thread's run loop until bytes arrive (keeps the same blocking
    API as a socket for buds.py)."""

    def __init__(self, mac, channel, timeout):
        import queue

        import objc
        from Foundation import NSObject
        from IOBluetooth import IOBluetoothDevice

        q = queue.Queue()

        class Delegate(NSObject):
            def rfcommChannelData_data_length_(self, ch, data, length):
                q.put(bytes(data.as_buffer(length)) if hasattr(data, "as_buffer") else bytes(data[:length]))

            def rfcommChannelClosed_(self, ch):
                q.put(b"")

        self._q, self._timeout = q, timeout
        self._delegate = Delegate.alloc().init()
        self._dev = IOBluetoothDevice.deviceWithAddressString_(mac.replace(":", "-"))
        if self._dev is None:
            raise OSError(f"unknown device {mac}")
        res, self._ch = self._dev.openRFCOMMChannelSync_withChannelID_delegate_(None, channel, self._delegate)
        if res != 0 or self._ch is None:  # kIOReturnSuccess
            raise OSError(f"RFCOMM channel {channel} failed ({res:#x})")
        self._objc = objc

    def settimeout(self, t):
        self._timeout = t

    def send(self, data: bytes):
        if self._ch.writeSync_length_(data, len(data)) != 0:
            raise OSError("RFCOMM write failed")

    def recv(self, n=1024):
        import queue
        import time

        from Foundation import NSDate, NSRunLoop

        end = time.monotonic() + (self._timeout or 0)
        while True:
            try:
                return self._q.get_nowait()
            except queue.Empty:
                pass
            if time.monotonic() >= end:
                raise TimeoutError
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

    def close(self):
        try:
            self._ch.closeChannel()
            self._dev.closeConnection()
        except Exception:
            pass


if __name__ == "__main__":
    pnp = ("CMF Buds Pro 2|BTHENUM\\DEV_0A1B2C3D4E5F\\7&ABCDEF0&0&BLUETOOTHDEVICE_0A1B2C3D4E5F\n"
           "OnePlus Nord Buds 2r|BTHENUM\\DEV_B0A3F228E4E6\\7&X\n"
           "Nothing Ear (a)|BTHENUM\\DEV_AABBCCDDEEFF\\7&Y\n")
    assert parse_pnp(pnp) == [("CMF Buds Pro 2", "0A:1B:2C:3D:4E:5F"), ("Nothing Ear (a)", "AA:BB:CC:DD:EE:FF")]
    ctl = ("Device 2C:BE:EB:11:22:33 Nothing Headphone (1)\n"
           "Device 00:11:22:33:44:55 JBL Flip 5\n"
           "Device AA:BB:CC:DD:EE:01 CMF Buds 2a\n")
    assert parse_bluetoothctl(ctl) == [("Nothing Headphone (1)", "2C:BE:EB:11:22:33"), ("CMF Buds 2a", "AA:BB:CC:DD:EE:01")]
    # the RFCOMM wrapper must be constructible and send whole frames (v1.0.0-1.0.3 crashed the connect thread here)
    a, b = socket.socketpair()
    w = _Sock(a.family, a.type, fileno=a.detach())
    assert w.send(b"\x55" * 9) == 9 and b.recv(16) == b"\x55" * 9
    w.close(); b.close()
    print("ok; paired here:", paired_devices())
