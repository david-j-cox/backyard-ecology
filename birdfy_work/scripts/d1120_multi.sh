#!/bin/sh
# d1120: HHMMSS TAG CROP S1-E1 S2-E2 ... -> one 15 fps sheet per window (tag_i)
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
c=$1; t=$2; cr=$3; shift 3; i=0
for w in "$@"; do i=$((i+1)); s=${w%-*}; e=${w#*-}
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-20_$c.mp4 $W/sheets/2026-11-20/${c}_${t}$i.jpg --start $s --end $e --fps 15 --cols 8 --width 200 --crop $cr | sed 's|.*/||'
done
