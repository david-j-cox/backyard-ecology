#!/bin/sh
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
c=$1
f=$W/raw_clips/2026-11-10_$c.mp4
d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
s=0; i=0
while awk "BEGIN{exit !($s < $d)}"; do
  e=$(awk "BEGIN{print $s+7.5}")
  /usr/local/bin/python3 -I $W/scripts/f2_sheetg.py "$f" $W/sheets/2026-11-10/${c}_4fps_$i.jpg --start $s --end $e --fps 4 --cols 6 --width 320 | sed 's|.*/||'
  s=$e; i=$((i+1))
done
