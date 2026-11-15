#!/bin/sh
# usage: d1112_z.sh HHMMSS START END [CROP x,y,w,h] [TAG] -> 15 fps zoom sheet for 2026-11-12
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
C=2026-11-12_$1
CROP=${4:-0,0,2304,1296}
TAG=${5:-z}
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/$C.mp4 $W/sheets/2026-11-12/${1}_${TAG}_$2.jpg --start $2 --end $3 --fps 15 --cols 6 --width 300 --crop $CROP | sed 's|.*/||'
