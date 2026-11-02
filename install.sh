#!/bin/sh
# BudsDesk installer for Linux:  curl -fsSL https://raw.githubusercontent.com/Prateek1771/budsdesk/main/install.sh | sh
# Installs the latest release for the current user (no sudo): ~/.local/share/budsdesk + menu entry.
set -eu

REPO=Prateek1771/budsdesk
URL="https://github.com/$REPO/releases/latest/download"

case "$(uname -s)" in
  Darwin) echo "On macOS, download the DMG instead: $URL/BudsDesk.dmg"; exit 1 ;;
  Linux) ;;
  *) echo "Unsupported OS: $(uname -s). See https://github.com/$REPO"; exit 1 ;;
esac
[ "$(uname -m)" = x86_64 ] || { echo "Prebuilt binaries are x86_64 only; run from source instead: https://github.com/$REPO#run-from-source"; exit 1; }

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/budsdesk" BIN="$HOME/.local/bin"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

echo "Downloading BudsDesk…"
curl -fL --progress-bar "$URL/BudsDesk-linux.tar.gz" -o "$TMP/b.tgz"
rm -rf "$DEST"; mkdir -p "$DEST" "$BIN" "$DATA/applications" "$DATA/icons/hicolor/512x512/apps"
tar -xzf "$TMP/b.tgz" -C "$DEST" --strip-components=1
ln -sf "$DEST/BudsDesk" "$BIN/budsdesk"
cp "$DEST/icon.png" "$DATA/icons/hicolor/512x512/apps/budsdesk.png" 2>/dev/null || true

cat > "$DATA/applications/budsdesk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=BudsDesk
Comment=Control Nothing / CMF earbuds and headphones
Exec=$DEST/BudsDesk
Icon=budsdesk
Categories=AudioVideo;Audio;Settings;
EOF

echo "Installed. Open BudsDesk from your app menu, or run: budsdesk"
command -v bluetoothctl >/dev/null 2>&1 || echo "Note: bluetoothctl not found; install BlueZ (e.g. sudo apt install bluez) so BudsDesk can find paired devices."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: add $BIN to your PATH to use the 'budsdesk' command." ;; esac
echo "Uninstall: rm -rf \"$DEST\" \"$BIN/budsdesk\" \"$DATA/applications/budsdesk.desktop\""
