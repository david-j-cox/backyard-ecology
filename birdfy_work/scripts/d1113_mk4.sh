#!/bin/sh
# 4 fps overview sheets in 10 s chunks: d1113_mk4.sh HHMMSS
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
C=$W/raw_clips/2026-11-13_$1.mp4
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $C)
s=0
while [ $(echo "$s < $D" | bc) -eq 1 ]; do
  e=$(echo "$s + 10" | bc)
  /usr/local/bin/python3 -I $W/scripts/sheet.py $C $W/sheets/2026-11-13/$1_4f_$s.jpg --start $s --end $e --fps 4 --cols 8 --width 240
  s=$e
done
/usr/local/bin/python3 -I $W/scripts/d1113_stack.py $W/sheets/2026-11-13/$1_4f_all.jpg $(ls $W/sheets/2026-11-13/$1_4f_*.jpg | grep -v _all | sort -t_ -k3 -n)
