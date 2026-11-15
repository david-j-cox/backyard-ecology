#!/bin/bash
# p3_mk4.sh HHMMSS -> 4 fps sheets (10 s each) for 2026-11-10 clip (fork part3 private copy)
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
f=$W/raw_clips/2026-11-10_$1.mp4
d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
i=0
for s in 0 10 20; do
  if awk "BEGIN{exit !($s < $d)}"; then
    /usr/local/bin/python3 -I $W/scripts/sheet.py "$f" $W/sheets/2026-11-10/${1}_4fps_$i.jpg --start $s --end $((s+10)) --fps 4 --cols 8 --width 240 | sed 's|.*/||'
  fi
  i=$((i+1))
done
