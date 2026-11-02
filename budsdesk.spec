# PyInstaller spec for all three OSes:  python -m PyInstaller --noconfirm budsdesk.spec
import sys

a = Analysis(["app.py"], datas=[("ui", "ui")], hiddenimports=["models", "platform_bt"])
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # onedir + .app bundle; macOS kills an app that touches Bluetooth without this usage string
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BudsDesk", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="BudsDesk")
    app = BUNDLE(coll, name="BudsDesk.app", bundle_identifier="io.github.prateek1771.budsdesk",
                 info_plist={"NSBluetoothAlwaysUsageDescription": "BudsDesk talks to your Nothing / CMF earbuds over Bluetooth.",
                             "NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="BudsDesk", console=False)
