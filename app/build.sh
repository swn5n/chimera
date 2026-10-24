#!/bin/bash
# Builds Chimera for macOS (Apple Silicon), Windows and Linux into ../dist.
# Needs Go 1.24+. Run from anywhere: ./build.sh
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(grep -E '^const Version' main.go | sed -E 's/.*"(.*)".*/\1/')
OUT=../dist
rm -rf "$OUT/Chimera.app" "$OUT/windows" "$OUT/linux"
mkdir -p "$OUT"
FLAGS=(-trimpath -ldflags "-s -w")

echo "Building Chimera $VERSION"
# macOS app bundle
APPDIR="$OUT/Chimera.app/Contents"
mkdir -p "$APPDIR/MacOS" "$APPDIR/Resources"
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build "${FLAGS[@]}" -o "$APPDIR/MacOS/chimera" .
sed "s/__VERSION__/$VERSION/g" packaging/Info.plist > "$APPDIR/Info.plist"
cp packaging/chimera.icns "$APPDIR/Resources/chimera.icns"
chmod +x "$APPDIR/MacOS/chimera"
# Sign the whole bundle (ad-hoc). Without this, Macs that receive the app over
# AirDrop, Messages or a download say it's "damaged".
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep -s - "$OUT/Chimera.app"
else
  python3 packaging/sign_macos.py "$OUT/Chimera.app"
fi

# Windows (no console window; the icon comes from rsrc_windows_amd64.syso)
mkdir -p "$OUT/windows"
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "-s -w -H windowsgui" -o "$OUT/windows/Chimera.exe" .

# Linux
mkdir -p "$OUT/linux"
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build "${FLAGS[@]}" -o "$OUT/linux/chimera" .

# Zips to send to friends
( cd "$OUT" && rm -f Chimera-mac.zip Chimera-windows.zip Chimera-linux.tar.gz \
  && zip -qry Chimera-mac.zip Chimera.app \
  && ( cd windows && zip -q ../Chimera-windows.zip Chimera.exe ) \
  && tar -czf Chimera-linux.tar.gz -C linux chimera )
echo "Done:"
ls -la "$OUT"
