#!/bin/bash
# usage: zoom_0711.sh HHMMSS CROP S:E:TAG [S:E:TAG ...]   -> 15 fps zoom sheets
cd "$(dirname "$0")/.."
c=$1; crop=$2; shift 2
for w in "$@"; do IFS=: read s e t <<< "$w"
/usr/local/bin/python3 -I scripts/sheet.py raw_clips/2026-11-07_$c.mp4 sheets/2026-11-07/${c}_z$t.jpg --start $s --end $e --fps 15 --cols 8 --width 260 --crop $crop; done
