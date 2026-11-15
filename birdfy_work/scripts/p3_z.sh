#!/bin/bash
# p3_z.sh HHMMSS TAG START END [CROP] -> 15 fps zoom sheet (fork part3 private copy)
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-10_$1.mp4 $W/sheets/2026-11-10/${1}_z$2.jpg --start $3 --end $4 --fps 15 --cols 8 --width 240 --crop ${5:-0,150,2304,1146} | sed 's|.*/||'
