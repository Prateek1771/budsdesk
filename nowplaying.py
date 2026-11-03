"""What the computer is playing, plus transport controls (issue #6).

NowPlaying().get()  -> {title, artist, album, app, playing, pos, dur, art} | None   (pos/dur in seconds, art = URL or None)
NowPlaying().cmd(n) -> n in CMDS
NowPlaying().watch(cb) -> daemon thread, cb(info|None) on track / play-state change or a seek

Windows: Global System Media Transport Controls (pywinrt), every app that shows in the Windows media flyout.
macOS:   AppleScript for Spotify and Music.  Linux: MPRIS via `playerctl`.
Every backend is optional: missing library/tool -> available False, the tile shows an idle state, nothing crashes.
"""
import base64
import shutil
import subprocess
import sys
import threading
import time

CMDS = ("toggle", "next", "prev", "back10", "fwd10")  # back10/fwd10: seek, for apps that allow seeking but not skipping

_APPS = {"msedge": "Edge", "chrome": "Chrome", "brave": "Brave", "firefox": "Firefox", "308046b0af4a39cb": "Firefox",
         "spotify": "Spotify", "vlc": "VLC", "zunemusic": "Media Player", "opera": "Opera", "vivaldi": "Vivaldi"}


def _app_name(aumid):
    """'Spotify.exe' / 'SpotifyAB.SpotifyMusic_zpd...!Spotify' / 'MSEdge' -> a short human name."""
    a = (aumid or "").strip()
    low = a.lower()
    for k, v in _APPS.items():
        if k in low:
            return v
    a = a.split("!")[-1].split("\\")[-1]
    a = a[:-4] if a.lower().endswith(".exe") else a
    return a.split(".")[-1][:24] or "Media"


def _num(s):
    try:
        return float(str(s).strip().replace(",", "."))
    except ValueError:
        return 0.0


def _info(title, artist, album, app, playing, pos, dur, art, can=None):
    dur = max(0.0, dur)
    return {"can": can or {"next": True, "prev": True, "seek": True},"title": title or "", "artist": artist or "", "album": album or "", "app": app, "playing": bool(playing),
            "pos": round(min(max(0.0, pos), dur) if dur else max(0.0, pos), 1), "dur": round(dur, 1), "art": art or None}


def parse_playerctl(out):
    """playerctl --format '{{status}}\\t{{playerName}}\\t{{title}}\\t{{artist}}\\t{{album}}\\t{{position}}\\t{{mpris:length}}\\t{{mpris:artUrl}}'"""
    f = (out or "").rstrip("\n").split("\t")
    if len(f) < 8 or f[0] not in ("Playing", "Paused") or not (f[2] or f[3]):
        return None
    return _info(f[2], f[3], f[4], _app_name(f[1]), f[0] == "Playing", _num(f[5]) / 1e6, _num(f[6]) / 1e6, f[7])


def parse_osascript_np(out):
    """'app\\ttitle\\tartist\\talbum\\tstate\\tpos\\tdur_s\\tart' from _MAC_SCRIPT, or '' when nothing plays."""
    f = (out or "").rstrip("\n").split("\t")
    if len(f) < 8 or f[4] not in ("playing", "paused"):
        return None
    return _info(f[1], f[2], f[3], f[0], f[4] == "playing", _num(f[5]), _num(f[6]), f[7])


class _Win:
    def __init__(self):
        import asyncio
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M  # ImportError -> unavailable
        from winrt.windows.storage.streams import DataReader

        self._M, self._DR, self._art = M, DataReader, {}
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="gsmtc").start()
        self._run(self._mgr())

    def _run(self, coro, timeout=4):
        import asyncio
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def _mgr(self):
        if not getattr(self, "_m", None):
            self._m = await self._M.request_async()
        return self._m

    async def _get(self):
        s = (await self._mgr()).get_current_session()
        if not s:
            return None
        p = await s.try_get_media_properties_async()
        if not (p.title or p.artist):
            return None
        pb = s.get_playback_info()
        playing = pb.playback_status == 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
        pos, dur = self._pos(s, playing)
        c = pb.controls  # e.g. a single YouTube video: no next/prev, but seekable
        can = {"next": bool(c.is_next_enabled), "prev": bool(c.is_previous_enabled), "seek": bool(c.is_playback_position_enabled)}
        app = _app_name(s.source_app_user_model_id)
        key = (app, p.title, p.artist)
        if key not in self._art:
            self._art = {key: await self._thumb(p.thumbnail)}  # ponytail: one-entry cache, art is read once per track
        return _info(p.title, p.artist, p.album_title, app, playing, pos, dur, self._art[key], can)

    @staticmethod
    def _pos(s, playing):
        """(position, duration) in seconds; apps update the timeline sparsely, so extrapolate from its stamp while playing."""
        tl = s.get_timeline_properties()
        pos, dur = tl.position.total_seconds(), (tl.end_time - tl.start_time).total_seconds()
        if playing and tl.last_updated_time.year > 1601:
            from datetime import datetime, timezone
            pos += max(0.0, (datetime.now(timezone.utc) - tl.last_updated_time).total_seconds())
        return pos, dur

    async def _thumb(self, ref):
        if not ref:
            return None
        try:
            st = await ref.open_read_async()
            n = st.size
            if not n or n > 4_000_000:
                return None
            r = self._DR(st)
            await r.load_async(n)
            buf = bytearray(n)
            r.read_bytes(buf)
            return f"data:{st.content_type or 'image/jpeg'};base64," + base64.b64encode(bytes(buf)).decode()
        except Exception:
            return None

    async def _cmd(self, name):
        s = (await self._mgr()).get_current_session()
        if not s:
            return
        if name in ("back10", "fwd10"):
            pos, dur = self._pos(s, s.get_playback_info().playback_status == 4)
            to = max(0.0, pos + (10 if name == "fwd10" else -10))
            to = min(to, dur - 1) if dur > 1 else to
            await s.try_change_playback_position_async(int(to * 10_000_000))  # 100 ns ticks
        else:
            await {"toggle": s.try_toggle_play_pause_async, "next": s.try_skip_next_async, "prev": s.try_skip_previous_async}[name]()

    def get(self):
        return self._run(self._get())

    def cmd(self, name):
        self._run(self._cmd(name))


_MAC_SCRIPT = """
if application "Spotify" is running then
  tell application "Spotify"
    if player state is not stopped then return "Spotify" & tab & (name of current track) & tab & (artist of current track) & tab & (album of current track) & tab & (player state as text) & tab & (player position as text) & tab & ((duration of current track) / 1000 as text) & tab & (artwork url of current track)
  end tell
end if
if application "Music" is running then
  tell application "Music"
    if player state is not stopped then return "Music" & tab & (name of current track) & tab & (artist of current track) & tab & (album of current track) & tab & (player state as text) & tab & (player position as text) & tab & (duration of current track as text) & tab & ""
  end tell
end if
return ""
"""


class _Mac:  # ponytail: Spotify + Music only; system-wide needs mediaremote-adapter (macOS 15.4+ blocks MediaRemote), see #9
    def __init__(self):
        if not shutil.which("osascript"):
            raise ImportError("osascript missing")
        self._app = None

    def get(self):
        out = subprocess.run(["osascript", "-e", _MAC_SCRIPT], capture_output=True, text=True, timeout=4).stdout
        d = parse_osascript_np(out)
        self._app = d and d["app"]
        return d

    def cmd(self, name):
        if self._app in ("Spotify", "Music"):
            verb = {"toggle": "playpause", "next": "next track", "prev": "previous track",
                    "back10": "set player position to (player position - 10)", "fwd10": "set player position to (player position + 10)"}[name]
            subprocess.run(["osascript", "-e", f'tell application "{self._app}" to {verb}'], capture_output=True, timeout=4)


class _Linux:  # ponytail: shells out to playerctl; switch to dbus-next if playerctl turns out to be missing on many distros
    FMT = "{{status}}\t{{playerName}}\t{{title}}\t{{artist}}\t{{album}}\t{{position}}\t{{mpris:length}}\t{{mpris:artUrl}}"

    def __init__(self):
        if not shutil.which("playerctl"):
            raise ImportError("playerctl missing")

    def get(self):
        r = subprocess.run(["playerctl", "metadata", "--format", self.FMT], capture_output=True, text=True, timeout=4)
        d = parse_playerctl(r.stdout) if r.returncode == 0 else None
        if d and d["art"] and d["art"].startswith("file://"):  # the web view can't load file:// from http://127.0.0.1
            d["art"] = _inline_file(d["art"][7:])
        elif d and d["art"] and not d["art"].startswith("https://"):
            d["art"] = None
        return d

    def cmd(self, name):
        args = {"toggle": ["play-pause"], "next": ["next"], "prev": ["previous"], "back10": ["position", "10-"], "fwd10": ["position", "10+"]}[name]
        subprocess.run(["playerctl", *args], capture_output=True, timeout=4)


def _inline_file(path):
    from urllib.parse import unquote
    import mimetypes, os
    path = unquote(path)
    try:
        if os.path.getsize(path) > 4_000_000:
            return None
        with open(path, "rb") as f:
            return f"data:{mimetypes.guess_type(path)[0] or 'image/jpeg'};base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return None


class NowPlaying:
    def __init__(self):
        cls = {"win32": _Win, "darwin": _Mac}.get(sys.platform, _Linux)
        try:
            self._b = cls()
        except Exception:  # library/tool missing -> feature off
            self._b = None

    @property
    def available(self):
        return self._b is not None

    def get(self):
        try:
            return self._b.get() if self._b else None
        except Exception:
            return None

    def cmd(self, name):
        if self._b and name in CMDS:
            try:
                self._b.cmd(name)
            except Exception:
                pass

    def watch(self, callback, period=1.0):
        """Daemon thread: callback(info) when track / play state / art changes or the position jumps (a seek)."""
        if not self._b:
            return

        def loop():
            last, t0 = None, 0.0
            while True:
                d, now = self.get(), time.monotonic()
                key = d and (d["app"], d["title"], d["artist"], d["playing"], d["dur"], bool(d["art"]), str(d["can"]))
                was = last and (last["app"], last["title"], last["artist"], last["playing"], last["dur"], bool(last["art"]), str(last["can"]))
                expect = last and last["pos"] + (now - t0 if last["playing"] else 0)
                if key != was or (d and abs(d["pos"] - expect) > 3):
                    callback(d)
                    last, t0 = d, now
                elif d:
                    last, t0 = d, now  # keep the drift reference fresh
                time.sleep(period)

        threading.Thread(target=loop, daemon=True, name="nowplaying-watch").start()


if __name__ == "__main__":
    assert _app_name("Spotify.exe") == "Spotify" and _app_name("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "Spotify"
    assert _app_name("MSEdge") == "Edge" and _app_name("Chrome") == "Chrome" and _app_name("308046B0AF4A39CB") == "Firefox"
    assert _app_name("C:\\Apps\\foobar2000.exe") == "foobar2000" and _app_name("") == "Media"
    d = parse_playerctl("Playing\tspotify\tSong\tArtist\tAlbum\t65000000\t200000000\thttps://i.scdn.co/x\n")
    assert d.pop("can") == {"next": True, "prev": True, "seek": True}
    assert d == {"title": "Song", "artist": "Artist", "album": "Album", "app": "Spotify", "playing": True, "pos": 65.0, "dur": 200.0, "art": "https://i.scdn.co/x"}, d
    assert parse_playerctl("Paused\tfirefox\tVid\t\t\t\t\t\n")["playing"] is False and parse_playerctl("Paused\tfirefox\tVid\t\t\t\t\t\n")["dur"] == 0
    assert parse_playerctl("Stopped\tvlc\tx\ty\t\t0\t0\t\n") is None and parse_playerctl("") is None and parse_playerctl("No players found") is None
    m = parse_osascript_np("Music\tTrack\tArt\tAlb\tpaused\t12,5\t180\t\n")
    assert m["pos"] == 12.5 and m["dur"] == 180 and m["playing"] is False and m["art"] is None
    assert parse_osascript_np("") is None and parse_osascript_np("Spotify\ta\tb\tc\tstopped\t0\t0\t\n") is None
    assert _info("t", "a", "", "X", True, 500, 100, None)["pos"] == 100  # clamped to duration
    np = NowPlaying()
    live = np.get()
    print("ok; now playing:", {k: (v[:40] + "…" if isinstance(v, str) and len(v) > 40 else v) for k, v in live.items()} if live
          else "nothing" if np.available else "unavailable on this machine")
