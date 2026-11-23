#!/bin/sh
# d1119b: HHMMSS TAG START END FPS COLS WIDTH [CROP] -> zoom sheet with chosen size
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
cr=${8:-0,150,2304,1146}
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-19_$1.mp4 $W/sheets/2026-11-19b/${1}_w$2.jpg --start $3 --end $4 --fps $5 --cols $6 --width $7 --crop $cr | sed 's|.*/||'
