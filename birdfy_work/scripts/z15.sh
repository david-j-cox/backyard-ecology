#!/bin/sh
# usage: z15.sh CLIPSTEM START END [crop] [width] [cols] -> 15 fps zoom sheet
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
D=$(echo $1 | cut -c1-10)
CROP=${4:-0,400,2304,896}; WID=${5:-300}; COLS=${6:-8}
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/$1.mp4 $W/sheets/$D/${1}_z$2.jpg --start $2 --end $3 --fps 15 --cols $COLS --width $WID --crop $CROP | sed 's|.*/||'
