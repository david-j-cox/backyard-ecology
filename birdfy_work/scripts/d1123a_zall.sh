#!/bin/sh
# d1123a: HHMMSS CROP [CHUNK] -> 15 fps sheets over the whole clip in CHUNK-second pieces
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
f=$W/raw_clips/2026-11-23_$1.mp4
ch=${3:-4}
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $f)
s=0
while [ $(echo "$s < $dur" | bc) = 1 ]; do
  /usr/local/bin/python3 -I $W/scripts/sheet.py $f $W/sheets/2026-11-23a/${1}_all_$s.jpg --start $s --end $((s+ch)) --fps 15 --cols 10 --width 220 --crop $2 | sed 's|.*/||'
  s=$((s+ch))
done
