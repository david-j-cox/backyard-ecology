#!/bin/sh
# d1123a: HHMMSS TAG START END CROP [COLS] [WIDTH] -> 15 fps sheet
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-23_$1.mp4 $W/sheets/2026-11-23a/${1}_$2.jpg --start $3 --end $4 --fps 15 --cols ${6:-10} --width ${7:-220} --crop $5 | sed 's|.*/||'
