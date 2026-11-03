# PyInstaller spec for all three OSes:  python -m PyInstaller --noconfirm budsdesk.spec
import os
import re
import sys

a = Analysis(["app.py"], datas=[("ui", "ui")], hiddenimports=["models", "platform_bt", "audio", "localserver", "nowplaying", "focus"] + (["pycaw", "pycaw.pycaw", "comtypes", "comtypes.stream", "winrt.runtime", "winrt.windows.foundation", "winrt.windows.foundation.collections", "winrt.windows.media.control", "winrt.windows.storage.streams"] if sys.platform == "win32" else ["pulsectl"] if sys.platform == "linux" else []))

if sys.platform == "linux":
    # Libraries that must come from the user's system, never from the (older) build machine: they load the
    # host's GPU drivers, fonts config, display server and audio plugins. Bundling Ubuntu 22.04's copies broke
    # newer distros (issue #1: GLIBCXX_3.4.32 not found -> no EGL -> no window). Same idea as AppImage's excludelist.
    # xcb-util leaf libs (icccm, image, keysyms, render-util, cursor) stay bundled: Qt's xcb plugin needs them
    # and many distros don't install them; they only sit on top of the host's core libxcb.
    HOST = re.compile(r"lib(stdc\+\+|gcc_s|E?GL\w*|OpenGL|gbm|drm|va(-[a-z0-9]+)?|vulkan|fontconfig|freetype"
                      r"|wayland-[a-z]+|xkbcommon(-x11)?|X11(-xcb)?|Xext|Xrender|xshmfence"
                      r"|xcb(-(dri2|dri3|glx|present|sync|xfixes|randr|shm|render|xkb))?"
                      r"|glib-2|gio-2|gobject-2|gmodule-2|dbus-1|asound)(?![\w+-])")
    for name, host in [("libstdc++.so.6", 1), ("libEGL_mesa.so.0", 1), ("libxcb.so.1", 1), ("libxcb-render.so.0", 1),
                       ("libxcb-render-util.so.0", 0), ("libxcb-icccm.so.4", 0), ("libxcb-cursor.so.0", 0), ("libxcb-shape.so.0", 0),
                       ("libva-drm.so.2", 1), ("libwayland-client.so.0", 1), ("libQt6Gui.so.6", 0), ("libpython3.10.so.1.0", 0)]:
        assert bool(HOST.match(name)) == bool(host), name
    a.binaries = [b for b in a.binaries
                  if not (b[1].startswith(("/lib", "/usr/lib")) and HOST.match(os.path.basename(b[0])))]

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # onedir + .app bundle; macOS kills an app that touches Bluetooth without this usage string
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BudsDesk", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="BudsDesk")
    app = BUNDLE(coll, name="BudsDesk.app", icon="ui/icon.png", bundle_identifier="io.github.prateek1771.budsdesk",
                 info_plist={"NSBluetoothAlwaysUsageDescription": "BudsDesk talks to your Nothing / CMF earbuds over Bluetooth.",
                             "NSHighResolutionCapable": True,
                             # the UI is served from http://127.0.0.1 (#5); WKWebView needs this to load it
                             "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True}})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="BudsDesk", console=False, icon="ui/icon.ico")
