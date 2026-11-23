#!/bin/sh
# d1118: HHMMSS TAG START END CROP -> 4 fps cropped sheet (10 cols)
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-18_$1.mp4 $W/sheets/2026-11-18/${1}_c$2.jpg --start $3 --end $4 --fps 4 --cols 10 --width 190 --crop $5 | sed 's|.*/||'
