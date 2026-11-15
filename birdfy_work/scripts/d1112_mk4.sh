#!/bin/sh
# usage: d1112_mk4.sh HHMMSS  -> 4 fps sheets of 10 s each (40 frames, width 240) for 2026-11-12
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
C=2026-11-12_$1
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $W/raw_clips/$C.mp4)
for s in 0 10 20; do
  if [ $(echo "$s < $dur" | bc) = 1 ]; then
  /usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/$C.mp4 $W/sheets/2026-11-12/${1}_a$s.jpg --start $s --end $((s+10)) --fps 4 --cols 8 --width 240 | sed 's|.*/||'
  fi
done
