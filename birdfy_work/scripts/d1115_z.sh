#!/bin/sh
# d1115: HHMMSS TAG START END [CROP] -> 15 fps zoom sheet
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
cr=${5:-0,150,2304,1146}
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-15_$1.mp4 $W/sheets/2026-11-15/${1}_z$2.jpg --start $3 --end $4 --fps 15 --cols 8 --width 240 --crop $cr | sed 's|.*/||'
