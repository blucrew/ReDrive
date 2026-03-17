#!/usr/bin/env bash
# ── ReDrive Rider — macOS build script ────────────────────────────────────
# Requires: pip3 install pyinstaller
#           brew install create-dmg  (optional, falls back to hdiutil)

set -e
NAME="ReDriveRider"
VERSION="0.1.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/.."

echo "=== Building $NAME v$VERSION (macOS) ==="

cd "$ROOT"

# Step 1: PyInstaller .app bundle
pyinstaller --noconfirm --onefile --windowed \
  --name "$NAME" \
  "$ROOT/rider_app.py"

echo "=== .app built: dist/$NAME.app ==="

# Step 2: Package into .dmg
DMG_NAME="${NAME}-${VERSION}-mac.dmg"
STAGING="dist/dmg_staging"
rm -rf "$STAGING" "dist/$DMG_NAME"
mkdir -p "$STAGING"
cp -r "dist/${NAME}.app" "$STAGING/"

if command -v create-dmg &>/dev/null; then
  create-dmg \
    --volname "$NAME" \
    --window-size 540 360 \
    --icon-size 128 \
    --icon "${NAME}.app" 140 160 \
    --app-drop-link 400 160 \
    "dist/$DMG_NAME" \
    "$STAGING"
else
  # Fallback: plain hdiutil
  hdiutil create -volname "$NAME" -srcfolder "$STAGING" \
    -ov -format UDZO "dist/$DMG_NAME"
fi

echo "=== Done: dist/$DMG_NAME ==="
