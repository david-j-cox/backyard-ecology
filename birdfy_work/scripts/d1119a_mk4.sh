#!/bin/zsh
# usage: d1119a_mk4.sh HHMMSS  -> 4 fps sheets in 10 s chunks for 2026-11-19 clip
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
c=$1
clip=$W/raw_clips/2026-11-19_$c.mp4
dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $clip)
s=0
while (( s < dur )); do
  e=$(( s + 10 ))
  /usr/local/bin/python3 -I $W/scripts/sheet.py $clip $W/sheets/2026-11-19a/${c}_4f_${s}.jpg --start $s --end $e --fps 4 --cols 8 --width 240
  s=$e
done
