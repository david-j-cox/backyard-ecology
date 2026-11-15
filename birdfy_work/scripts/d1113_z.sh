#!/bin/sh
# 15 fps zoom: d1113_z.sh HHMMSS START END TAG [crop] [width] [cols]
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
CROP=${5:-0,0,2304,1296}
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-13_$1.mp4 $W/sheets/2026-11-13/$1_z_$4.jpg --start $2 --end $3 --fps 15 --cols ${7:-8} --width ${6:-240} --crop $CROP
