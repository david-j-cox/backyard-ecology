#!/bin/sh
# usage: b2_mk.sh CLIPSTEM TAG START END FPS COLS WIDTH [CROP]
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
C=""; [ -n "$8" ] && C="--crop $8"
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/$1.mp4 $W/blind2/sheets/$1_$2.jpg --start $3 --end $4 --fps $5 --cols $6 --width $7 $C
