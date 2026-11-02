"""System output volume (get / set / watch) on Windows, macOS and Linux — issue #2.

The buds never report volume over RFCOMM: the case dial (rotate = AVRCP volume) changes the *host's* master volume,
so that is what the Smart Dial gauge mirrors. Every backend is optional: Volume().get() returns None when nothing
works, and the UI shows "--" instead of crashing.

  Windows  pycaw  -> IAudioEndpointVolume (default render endpoint, re-acquired so switching outputs is picked up)
  macOS    osascript "get volume settings" / "set volume output volume N"
  Linux    wpctl (PipeWire), else pactl (PulseAudio / pipewire-pulse)
"""
import re
import shutil
import subprocess
import sys
import threading


def _run(cmd, timeout=2):
    kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console flash on Windows
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# ── output parsers (pure, unit-tested in __main__ on every OS) ──────────
def parse_wpctl(out):
    """'Volume: 0.42' / 'Volume: 0.42 [MUTED]' -> (0.42, muted)"""
    m = re.search(r"Volume:\s*([\d.]+)", out)
    return (min(1.0, float(m[1])), "[MUTED]" in out) if m else None


def parse_pactl(vol_out, mute_out):
    """'Volume: front-left: 27525 /  42% / ...' + 'Mute: no' -> (0.42, False). Averages the channels."""
    pcts = [int(p) for p in re.findall(r"(\d+)%", vol_out)]
    return (min(1.0, sum(pcts) / len(pcts) / 100), "yes" in mute_out.lower()) if pcts else None


def parse_osascript(out):
    """'42, false' -> (0.42, False); 'missing value' (no output device) -> None"""
    m = re.match(r"\s*(\d+)\s*,\s*(true|false)", out)
    return (int(m[1]) / 100, m[2] == "true") if m else None


# ── backends ────────────────────────────────────────────────────────────
class _Win:
    def __init__(self):
        from pycaw.pycaw import AudioUtilities  # noqa: F401  (ImportError -> backend unavailable)
        self._ev, self._tls = None, threading.local()

    def _endpoint(self, fresh=False):
        import comtypes
        from pycaw.pycaw import AudioUtilities
        if not getattr(self._tls, "com", False):
            comtypes.CoInitialize()  # COM is per thread (watcher thread, pywebview API threads)
            self._tls.com = True
        if fresh or getattr(self._tls, "ev", None) is None:
            self._tls.ev = AudioUtilities.GetSpeakers().EndpointVolume
        return self._tls.ev

    def get(self, fresh=False):
        try:
            ev = self._endpoint(fresh)
            return ev.GetMasterVolumeLevelScalar(), bool(ev.GetMute())
        except Exception:  # no output device / endpoint vanished (e.g. buds disconnected)
            self._tls.ev = None
            return None

    def set(self, level):
        try:
            self._endpoint().SetMasterVolumeLevelScalar(level, None)
        except Exception:
            self._tls.ev = None


class _Mac:
    def __init__(self):
        if not shutil.which("osascript"):
            raise ImportError("osascript missing")

    def get(self, fresh=False):
        return parse_osascript(_run(["osascript", "-e",
                                     "set s to get volume settings\nreturn (output volume of s as text) & \", \" & (output muted of s as text)"]))

    def set(self, level):
        _run(["osascript", "-e", f"set volume output volume {round(level * 100)}"])


class _Linux:
    def __init__(self):
        self.tool = "wpctl" if shutil.which("wpctl") else "pactl" if shutil.which("pactl") else None
        if not self.tool:
            raise ImportError("no wpctl/pactl")

    def get(self, fresh=False):
        if self.tool == "wpctl":
            return parse_wpctl(_run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]))
        return parse_pactl(_run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]), _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]))

    def set(self, level):
        if self.tool == "wpctl":
            _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.3f}"])
        else:
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{round(level * 100)}%"])


class Volume:
    def __init__(self):
        cls = {"win32": _Win, "darwin": _Mac}.get(sys.platform, _Linux)
        try:
            self._b = cls()
        except Exception:  # library or tool missing: feature off, app fine
            self._b = None
        self._last = None

    @property
    def available(self):
        return self._b is not None and self._b.get() is not None

    def get(self):
        """(level 0..1, muted) or None"""
        return self._b.get() if self._b else None

    def set(self, level):
        if self._b:
            self._b.set(max(0.0, min(1.0, float(level))))

    def watch(self, callback, hz=8):
        """Daemon thread: calls callback(level, muted) only when the value changes (rounded to 1%)."""
        if not self._b:
            return
        period = 1 / (hz if sys.platform == "win32" else min(hz, 4))  # subprocess backends: 4 Hz max

        def loop():
            n = 0
            while True:
                n += 1
                v = self._b.get(fresh=(n % int(3 / period) == 0))  # re-acquire the default output every ~3 s
                key = (round(v[0], 2), v[1]) if v else None
                if key != self._last:
                    self._last = key
                    try:
                        callback(*(v if v else (None, False)))
                    except Exception:
                        pass
                threading.Event().wait(period)

        threading.Thread(target=loop, daemon=True, name="volume-watch").start()


if __name__ == "__main__":
    assert parse_wpctl("Volume: 0.42\n") == (0.42, False)
    assert parse_wpctl("Volume: 0.35 [MUTED]\n") == (0.35, True)
    assert parse_wpctl("Volume: 1.50\n") == (1.0, False)  # over-amplified sinks clamp to 100 %
    assert parse_wpctl("") is None
    assert parse_pactl("Volume: front-left: 27525 /  42% / -22.58 dB,   front-right: 27525 /  44% / -22.58 dB\n",
                       "Mute: no\n") == (0.43, False)
    assert parse_pactl("", "Mute: yes") is None
    assert parse_osascript("42, false") == (0.42, False) and parse_osascript("0, true") == (0.0, True)
    assert parse_osascript("missing value, missing value") is None
    v = Volume()
    print("ok; live volume:", v.get() if v.get() is not None else "unavailable on this machine")
