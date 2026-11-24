#!/bin/bash
# multi-window 15 fps zooms: d1113_zm.sh HHMMSS CROP WIDTH COLS s1:e1 s2:e2 ...  (tags a,b,c...)
W=/Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
clip=$1; crop=$2; wd=$3; cols=$4; shift 4
tags=(a b c d e f g h i j k l m n o p q r s t u v w x y z)
i=0
for win in "$@"; do
  s=${win%%:*}; e=${win##*:}
  /usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-13_$clip.mp4 $W/sheets/2026-11-13/${clip}_z_${tags[$i]}.jpg --start $s --end $e --fps 15 --cols $cols --width $wd --crop $crop
  i=$((i+1))
done
