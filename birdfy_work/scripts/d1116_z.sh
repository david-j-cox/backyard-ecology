#!/bin/sh
# d1116_z.sh HHMMSS TAG START END [CROP] [FPS] [COLS] [WIDTH] -> zoom sheet for a 2026-11-16 clip
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-16_$1.mp4 $W/sheets/2026-11-16/${1}_z$2.jpg --start $3 --end $4 --fps ${6:-15} --cols ${7:-8} --width ${8:-240} --crop ${5:-0,150,2304,1146} | sed 's|.*/||'
