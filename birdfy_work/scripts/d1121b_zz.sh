#!/bin/sh
# d1121b: HHMMSS TAG START END CROP [FPS] [COLS] [WIDTH] -> zoom sheet for a 2026-11-21 clip
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-21_$1.mp4 $W/sheets/2026-11-21b/${1}_z$2.jpg --start $3 --end $4 --crop $5 --fps ${6:-15} --cols ${7:-10} --width ${8:-192} | sed 's|.*/||'
