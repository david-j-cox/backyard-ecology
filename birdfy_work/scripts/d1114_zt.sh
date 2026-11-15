#!/bin/sh
# d1114_zt.sh HHMMSS TAG START END CROP [FPS] [COLS] [WIDTH] -> tight zoom sheet for a 2026-11-14 clip
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-14_$1.mp4 $W/sheets/2026-11-14/${1}_t$2.jpg --start $3 --end $4 --fps ${6:-15} --cols ${7:-8} --width ${8:-240} --crop $5 | sed 's|.*/||'
