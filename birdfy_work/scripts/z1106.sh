#!/bin/bash
# z1106.sh CLIPID NAME START END CROP [FPS] [WIDTH] [COLS]   (2026-11-06 only)
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-06_$1.mp4 $W/sheets/2026-11-06/$1_$2.jpg --start $3 --end $4 --crop $5 --fps ${6:-15} --width ${7:-240} --cols ${8:-8}
