#!/bin/bash
# usage: mk4.sh TAG CLIP DUR  -> 4 fps sheets in 10 s chunks, with true centre line
cd /Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
tag=$1; clip=$2; dur=$3
s=0
while /usr/local/bin/python3 -c "import sys; sys.exit(0 if $s < $dur else 1)"; do
  e=$(/usr/local/bin/python3 -c "print(min($s+10,$dur))")
  /usr/local/bin/python3 -I blind/sheet2.py raw_clips/$clip blind/sheets/${tag}_4f_$s.jpg --start $s --end $e --fps 4 --cols 8 --width 360
  s=$((s+10))
done
