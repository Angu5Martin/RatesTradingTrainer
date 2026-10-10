#!/bin/bash
# Rebuild AppIcon.icns (and the 1024px preview AppIcon-1024.png) from the SVG artwork. Same pipeline as the A1 Español app: headless Chrome renders the SVG, iconutil packs it.
#
#   scripts/assets/make_icon.sh
#
# icon.svg is the master artwork. icon_small.svg is the simplified version (no grid, one curve, heavier line) used at 16, 32 and 64 px so it stays legible in the Dock and Finder lists.
# Each size is rendered natively from the SVG rather than scaled down from one big bitmap. Needs Google Chrome, sips and iconutil (all present on a standard Mac with Chrome).
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "Google Chrome is needed to render the icon (looked for: $CHROME)" >&2; exit 1; }
command -v iconutil >/dev/null || { echo "iconutil is needed (it ships with macOS)" >&2; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

render() {   # render SIZE SVG OUT.png : the SVG at SIZE x SIZE pixels with a transparent background
  local size="$1" svg="$2" out="$3"
  printf '<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:transparent}img{display:block;width:%spx;height:%spx}</style><img src="file://%s">' "$size" "$size" "$svg" > "$WORK/page-$size.html"
  "$CHROME" --headless --disable-gpu --hide-scrollbars --force-device-scale-factor=1 --default-background-color=00000000 \
    --window-size="$size,$size" --screenshot="$out" "file://$WORK/page-$size.html" >/dev/null 2>&1
  local w; w="$(sips -g pixelWidth "$out" 2>/dev/null | awk '/pixelWidth/ {print $2}')"
  [ "$w" = "$size" ] || { echo "rendering $size px gave a ${w:-missing} px image" >&2; exit 1; }
}

mkdir "$WORK/AppIcon.iconset"
for px in 16 32 64 128 256 512 1024; do
  src="$HERE/icon.svg"; [ "$px" -le 64 ] && src="$HERE/icon_small.svg"
  render "$px" "$src" "$WORK/$px.png"
done
S="$WORK/AppIcon.iconset"
cp "$WORK/16.png"   "$S/icon_16x16.png";      cp "$WORK/32.png"   "$S/icon_16x16@2x.png"
cp "$WORK/32.png"   "$S/icon_32x32.png";      cp "$WORK/64.png"   "$S/icon_32x32@2x.png"
cp "$WORK/128.png"  "$S/icon_128x128.png";    cp "$WORK/256.png"  "$S/icon_128x128@2x.png"
cp "$WORK/256.png"  "$S/icon_256x256.png";    cp "$WORK/512.png"  "$S/icon_256x256@2x.png"
cp "$WORK/512.png"  "$S/icon_512x512.png";    cp "$WORK/1024.png" "$S/icon_512x512@2x.png"
iconutil -c icns "$S" -o "$HERE/AppIcon.icns"
cp "$WORK/1024.png" "$HERE/AppIcon-1024.png"
echo "Wrote $HERE/AppIcon.icns and $HERE/AppIcon-1024.png"
