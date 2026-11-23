#!/bin/sh
# d1115: HHMMSS [CROP] -> 15 fps sheets (10 s each, 1 s per row) over the whole clip
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
f=$W/raw_clips/2026-11-15_$1.mp4
cr=${2:-0,150,1500,1146}
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $f)
for s in 0 10 20; do
  if [ $(echo "$s < $dur" | bc) = 1 ]; then
  /usr/local/bin/python3 -I $W/scripts/sheet.py $f $W/sheets/2026-11-15/${1}_15all_$s.jpg --start $s --end $((s+10)) --fps 15 --cols 15 --width 128 --crop $cr | sed 's|.*/||'
  fi
done
