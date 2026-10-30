#!/bin/bash
# Build dist/Jarvis-<version>-<arch>.dmg on a Mac.   bash platform/mac/build.sh [arm64|x86_64]
# The app carries its own Python (python-build-standalone); packages and speech models install on first run.
set -euo pipefail
ARCH="${1:-$(uname -m)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VER="$(cat "$ROOT/VERSION")"
PBS_TAG="${PBS_TAG:-20241016}"; PY_VER="${PY_VER:-3.12.7}"
case "$ARCH" in arm64|aarch64) TRIPLE=aarch64-apple-darwin;; x86_64) TRIPLE=x86_64-apple-darwin;; *) echo "unknown arch $ARCH"; exit 1;; esac
OUT="$ROOT/dist"; APP="$OUT/Jarvis.app"; RES="$APP/Contents/Resources"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$RES"

sed "s/@VERSION@/$VER/g" "$ROOT/platform/mac/Info.plist" > "$APP/Contents/Info.plist"
cp "$ROOT/platform/mac/Jarvis" "$APP/Contents/MacOS/Jarvis"; chmod 755 "$APP/Contents/MacOS/Jarvis"
cp "$ROOT/platform/mac/Jarvis.icns" "$RES/Jarvis.icns"
for x in jarvis hud app models-bundle; do rsync -a --exclude __pycache__ --exclude '*.pyc' "$ROOT/$x" "$RES/"; done
cp "$ROOT/requirements.txt" "$ROOT/VERSION" "$ROOT/LICENSE" "$ROOT/NOTICE.md" "$RES/"

PBS="cpython-$PY_VER+$PBS_TAG-$TRIPLE-install_only.tar.gz"
mkdir -p "$OUT/cache"
[ -s "$OUT/cache/$PBS" ] || curl -L --fail -o "$OUT/cache/$PBS" "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_TAG/$PBS"
tar xzf "$OUT/cache/$PBS" -C "$RES"                       # -> Resources/python

codesign --force --deep -s - "$APP" 2>/dev/null || echo "(ad-hoc signing skipped)"
DMG="$OUT/Jarvis-$VER-$ARCH.dmg"; STAGE="$OUT/dmg"
rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"; cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Jarvis $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"
echo "built $DMG"
