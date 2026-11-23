#!/bin/zsh
# usage: d1119a_z.sh HHMMSS START END [crop] [cols] [width] -> 15 fps zoom
W=/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work
c=$1; s=$2; e=$3; crop=${4:-}; cols=${5:-8}; wd=${6:-280}
args=()
[[ -n $crop ]] && args=(--crop $crop)
/usr/local/bin/python3 -I $W/scripts/sheet.py $W/raw_clips/2026-11-19_$c.mp4 $W/sheets/2026-11-19a/${c}_z_${s}_${e}.jpg --start $s --end $e --fps 15 --cols $cols --width $wd $args
