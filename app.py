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

import audio
import buds
import localserver
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
MEDIA_DIR = os.path.join(PREFS_DIR, "media")  # user images/videos for the media tile (#5), served at /media/
MEDIA_TYPES = {"image": ("Images (*.jpg;*.jpeg;*.png;*.gif;*.webp;*.avif)",), "video": ("Videos (*.mp4;*.webm;*.mov;*.m4v)",)}


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
    def __init__(self, session: Session, volume: "audio.Volume", meter: "audio.Meter"):
        self._s, self._vol, self._meter = session, volume, meter
        self._window = None  # set after create_window (needed for native file dialogs)

    def _b(self):
        return self._s.b

    # prefs
    def prefs(self):
        return _read(LAYOUT)

    def save_prefs(self, prefs):
        _write(LAYOUT, prefs)

    def meta(self):
        return {"types": buds.GESTURE_TYPES, "actions": buds.ACTIONS, "generic_actions": buds.models.GENERIC_ACTIONS,
                "platform": sys.platform, "audio": self._vol.available,
                "levels": self._meter.available}

    # system volume (#2): the Smart Dial gauge mirrors it, dragging the gauge sets it
    def volume(self):
        v = self._vol.get()
        return {"v": v[0], "m": v[1]} if v else None

    def set_volume(self, level):
        self._vol.set(level)

    # media tile (#5): pick images/videos -> copied into MEDIA_DIR -> served by the local server at /media/<name>
    def pick_media(self, kind="image", multiple=False):
        import shutil, uuid
        if kind not in MEDIA_TYPES or not self._window:
            return []
        paths = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=bool(multiple), file_types=MEDIA_TYPES[kind]) or []
        os.makedirs(MEDIA_DIR, exist_ok=True)
        out = []
        for src in paths:
            name = f"{uuid.uuid4().hex[:10]}{os.path.splitext(src)[1].lower()}"
            shutil.copyfile(src, os.path.join(MEDIA_DIR, name))
            out.append("/media/" + name)
        return out

    def forget_media(self, urls):
        """Delete copied files the media tile no longer uses (only names inside MEDIA_DIR)."""
        for u in urls or []:
            name = os.path.basename(str(u))
            if str(u).startswith("/media/") and name and os.path.isfile(os.path.join(MEDIA_DIR, name)):
                os.remove(os.path.join(MEDIA_DIR, name))

    # output level (#3 waves): latest (left, right) peak 0..1, sampled ~30 Hz off-thread; None = unavailable
    def levels(self):
        lv = self._meter.levels()
        return [round(lv[0], 3), round(lv[1], 3)] if lv else None

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
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(os.path.join(HERE, "ui", "tray.png"))  # logo small-size cut on its tile (docs/logo)

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
    volume, meter = audio.Volume(), audio.Meter().start()
    # UI over http://127.0.0.1:<random> (not file://): YouTube embeds need a referrer (#5) and /media/ serves user files
    server = localserver.LocalServer(os.path.join(HERE, "ui"), MEDIA_DIR)
    api = Api(session, volume, meter)
    window = webview.create_window(APP, server.url + "/index.html", js_api=api,
                                   width=1060, height=860, min_size=(420, 560), background_color="#e7e8ec")
    api._window = window

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

    def on_volume(level, muted):  # watcher thread; pushes only on change
        if window and level is not None:
            try:
                window.evaluate_js(f"window.volTick && volTick({level:.4f}, {str(bool(muted)).lower()})")
            except Exception:
                pass
    volume.watch(on_volume)
    icon = make_tray(window, session, quit_app)
    webview.start(lambda: session.pick(sys.argv[1] if len(sys.argv) > 1 else None),
                  **({"gui": "qt", "icon": os.path.join(HERE, "ui", "icon.png")} if sys.platform == "linux" else {}))
    # Linux: the bundle ships Qt (skip the GTK probe) and Qt takes a PNG window icon. Never pass icon= elsewhere:
    # on Windows pywebview hands it to System.Drawing.Icon, which only reads .ico and crashed v1.0.2 at launch.


if __name__ == "__main__":
    main()
