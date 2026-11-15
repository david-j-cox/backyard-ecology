#!/bin/sh
# usage: mk4.sh CLIPSTEM  -> 4 fps sheets of 10 s each
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
D=$(echo $1 | cut -c1-10)
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $W/raw_clips/$1.mp4)
for s in 0 10 20; do
  if [ $(echo "$s < $dur" | bc) = 1 ]; then
  /usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/$1.mp4 $W/sheets/$D/${1}_a$s.jpg --start $s --end $((s+10)) --fps 4 --cols 8 --width 240 | sed 's|.*/||'
  fi
done
