#!/bin/bash
# cap.sh <app> <screen-id>   -> screens/<app>/<screen-id>.png (iPhone Mirroring window capture; set WID to the mirror window id)
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HERE/screens/$1"
OUT="$HERE/screens/$1/$2.png"
WID=${WID:-44141}
screencapture -x -o -l $WID "$OUT"
sips -g pixelWidth -g pixelHeight "$OUT" | tail -2 | tr '\n' ' '; echo "$OUT"
