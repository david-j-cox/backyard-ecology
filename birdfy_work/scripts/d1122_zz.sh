#!/bin/sh
# d1122: HHMMSS CROP TAG:START:END [TAG:START:END ...] -> 15 fps zoom sheets (width 300, 6 cols)
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
h=$1; cr=$2; shift 2
for t in "$@"; do
  tag=${t%%:*}; r=${t#*:}; s=${r%%:*}; e=${r#*:}
  /usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-22_$h.mp4 $W/sheets/2026-11-22/${h}_z$tag.jpg --start $s --end $e --fps 15 --cols ${COLS:-6} --width ${WID:-300} --crop $cr | sed 's|.*/||'
done
