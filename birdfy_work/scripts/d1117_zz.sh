#!/bin/sh
# d1117: HHMMSS CROP START1 END1 [START2 END2 ...] -> one 15 fps sheet per window, 7 cols x 250 px
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
c=$1; cr=$2; shift 2
while [ $# -ge 2 ]; do
  /usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-17_$c.mp4 $W/sheets/2026-11-17/${c}_p$1.jpg --start $1 --end $2 --fps 15 --cols 7 --width 250 --crop $cr | sed 's|.*/||'
  shift 2
done
