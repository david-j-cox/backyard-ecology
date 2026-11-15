#!/bin/bash
# usage: z.sh TAG CLIP START END [CROP] [COLS] [WIDTH] [FPS] -> zoom sheet with true centre line
cd /Users/davidjcox/Documents/campus-worktrees/e13dfb02/birdfy_work
crop=${5:-0,300,2304,996}; cols=${6:-8}; w=${7:-400}; fps=${8:-15}
/usr/local/bin/python3 -I blind/sheet2.py raw_clips/$2 blind/sheets/${1}_z${fps}_$3.jpg --start $3 --end $4 --fps $fps --cols $cols --width $w --crop $crop
