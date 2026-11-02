"""BudsDesk: desktop controller for Nothing / CMF earbuds & headphones (Windows, macOS, Linux).

pywebview window (WebView2 / WKWebView / Qt WebEngine) + optional tray icon.
"""
import json
import os
import sys

if sys.platform == "linux":
    # Qt WebEngine needs working EGL/OpenGL, which fails on many setups (NVIDIA + Wayland, VMs, WSL), leaving no
    # window at all (issue #1). This small UI renders fine on the CPU, so default to software; BUDSDESK_GPU=1 opts out.
    # setdefault: anything the user exports wins.
    if os.environ.get("BUDSDESK_GPU") != "1":
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")  # fall back to XWayland if native Wayland can't start

import webview

import buds
import platform_bt

APP = "BudsDesk"
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def prefs_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP if sys.platform != "linux" else APP.lower())
    os.makedirs(d, exist_ok=True)
    old = os.path.join(os.environ.get("APPDATA", ""), "CMFControl", "layout.json")  # pre-rename location
    new = os.path.join(d, "layout.json")
    if sys.platform == "win32" and os.path.exists(old) and not os.path.exists(new):
        os.replace(old, new)
    return d


PREFS_DIR = prefs_dir()
LAYOUT, DEVICE = os.path.join(PREFS_DIR, "layout.json"), os.path.join(PREFS_DIR, "device.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)  # atomic: a crash mid-write can't corrupt the file


class Session:
    """Owns the one live Buds connection; can switch to another paired device."""

    def __init__(self, on_change):
        self.on_change, self.b, self.devices = on_change, None, []

    def scan(self):
        self.devices = platform_bt.paired_devices()
        return self.devices

    def pick(self, mac=None):
        """argv/explicit mac > last used > first paired Nothing/CMF device."""
        last = (_read(DEVICE) or {}).get("mac")
        macs = [m for _, m in self.devices]
        mac = mac or (last if last in macs else None) or (macs[0] if macs else None)
        if not mac:
            return None
        if self.b:
            self.b.stop()
        name = next((n for n, m in self.devices if m == mac), "")
        self.b = buds.Buds(mac, name, self.on_change).start()
        _write(DEVICE, {"mac": mac, "name": name})
        return mac

    def state(self):
        if self.b:
            return self.b.state
        s = buds.new_state()
        s["status"] = "nodevice"
        return s


class Api:
    def __init__(self, session: Session):
        self._s = session

    def _b(self):
        return self._s.b

    # prefs
    def prefs(self):
        return _read(LAYOUT)

    def save_prefs(self, prefs):
        _write(LAYOUT, prefs)

    def meta(self):
        return {"types": buds.GESTURE_TYPES, "actions": buds.ACTIONS, "generic_actions": buds.models.GENERIC_ACTIONS,
                "platform": sys.platform}

    def state(self):
        return self._s.state()

    # devices
    def devices(self):
        cur = self._b().mac if self._b() else None
        return [{"name": n, "mac": m, "current": m == cur} for n, m in self._s.scan()]

    def select(self, mac):
        self._s.pick(mac)
        return self.state()

    # device commands (no-ops when nothing is connected)
    def _do(self, fn, *a):
        if self._b():
            getattr(self._b(), fn)(*a)

    def anc(self, mode): self._do("set_anc", mode)
    def listening(self, idx): self._do("set_listening", int(idx))
    def custom_eq(self, bass, mid, treble): self._do("set_custom_eq", bass, mid, treble)
    def bass(self, on, level): self._do("set_bass", bool(on), level)
    def in_ear(self, on): self._do("set_in_ear", bool(on))
    def latency(self, on): self._do("set_latency", bool(on))
    def gesture(self, device, button, gtype, action): self._do("set_gesture", int(device), int(button), int(gtype), int(action))
    def ring(self, which): self._do("ring", which)


_lock_fd = None  # kept open for the process lifetime (POSIX flock)


def single_instance() -> bool:
    """Only one copy may run: the buds accept one RFCOMM controller, so a second copy just steals it."""
    global _lock_fd
    if sys.platform == "win32":
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.CreateMutexW(None, False, "BudsDesk.SingleInstance")
        return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    import fcntl

    _lock_fd = open(os.path.join(PREFS_DIR, ".lock"), "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def make_tray(window, session, quit_app):
    """Tray icon on Windows/Linux. macOS: none (pystray and pywebview both need the main thread)."""
    if sys.platform == "darwin":
        return None
    if sys.platform == "linux":
        try:  # pystray's only working Linux tray is AppIndicator; its X11 fallback can't dock on Wayland (issue #1)
            import gi  # noqa: F401
        except ImportError:
            return None
        os.environ.setdefault("PYSTRAY_BACKEND", "appindicator")
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), 16, fill=(11, 11, 12))
    for x, y in [(22, 22), (42, 22), (22, 42), (42, 42)]:
        d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(255, 79, 18) if (x, y) == (42, 22) else (244, 244, 245))

    def anc_item(label, mode):
        return pystray.MenuItem(label, lambda: session.b and session.b.set_anc(mode),
                                checked=lambda _: bool(session.b) and session.b.state["anc"] == mode, radio=True)

    icon = pystray.Icon("budsdesk", img, APP, pystray.Menu(
        pystray.MenuItem("Open", lambda: window.show(), default=True),
        pystray.Menu.SEPARATOR,
        anc_item("Noise cancelling", "high"), anc_item("Transparency", "transparency"), anc_item("Off", "off"),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    ))
    try:
        icon.run_detached()
    except Exception:  # no tray backend (e.g. Linux without AppIndicator)
        return None
    return icon


def main():
    if not single_instance():
        sys.exit(0)  # ponytail: silently exit; bring-to-front of the first window can come later if wanted
    window = icon = None
    quitting = False

    def on_change(state):
        if window:
            try:
                window.evaluate_js(f"window.render && render({json.dumps(state)})")
            except Exception:
                pass  # window not ready / hidden
        if icon:
            bat = state["battery"]
            parts = [f"{k[0].upper()} {bat[k]['pct']}%" for k in ("left", "right", "case", "unit") if k in bat]
            icon.title = f"{state['model']['name']} — " + (" · ".join(parts) or state["status"])

    session = Session(on_change)
    session.scan()
    window = webview.create_window(APP, os.path.join(HERE, "ui", "index.html"), js_api=Api(session),
                                   width=1060, height=860, min_size=(420, 560), background_color="#e7e8ec")

    def quit_app():
        nonlocal quitting
        quitting = True
        if icon:
            icon.stop()
        if session.b:
            session.b.stop()
        window.destroy()

    def on_closing():
        if quitting or not icon:
            if session.b:
                session.b.stop()
            return True  # no tray: closing quits
        window.hide()  # close button minimises to tray
        return False

    window.events.closing += on_closing
    icon = make_tray(window, session, quit_app)
    webview.start(lambda: session.pick(sys.argv[1] if len(sys.argv) > 1 else None),
                  gui="qt" if sys.platform == "linux" else None)  # Linux bundle ships Qt; skip the GTK probe


if __name__ == "__main__":
    main()
