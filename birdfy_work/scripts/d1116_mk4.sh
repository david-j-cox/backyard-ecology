#!/bin/sh
# d1116_mk4.sh HHMMSS [WIDTH] -> 4 fps sheets (10 s each) for a 2026-11-16 clip
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
f=$W/raw_clips/2026-11-16_$1.mp4
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $f)
for s in 0 10 20; do
  if [ $(echo "$s < $dur" | bc) = 1 ]; then
  /usr/local/bin/python3 -I $W/scripts/sheet.py $f $W/sheets/2026-11-16/${1}_4fps_$s.jpg --start $s --end $((s+10)) --fps 4 --cols 8 --width ${2:-240} | sed 's|.*/||'
  fi
done
