#!/bin/zsh
# Move Birdfy downloads (output*.mp4) from ~/Downloads into the staging folder,
# named by clip start time in America/New_York (creation_time - duration).
DEST="$1"; mkdir -p "$DEST"
setopt null_glob
while true; do
  for f in ~/Downloads/output*.mp4; do
    [[ -e "$f.crdownload" ]] && continue
    sleep 1
    ct=$(ffprobe -v error -show_entries format_tags=creation_time -of csv=p=0 "$f")
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
    [[ -z "$ct" || -z "$dur" ]] && continue
    end=$(TZ=UTC date -j -f "%Y-%m-%dT%H:%M:%S" "${ct%%.*}" +%s)
    start=$(( end - ${dur%%.*} ))
    name=$(TZ=America/New_York date -r $start +%Y-%m-%d_%H%M%S)
    out="$DEST/$name.mp4"; n=1
    while [[ -e "$out" ]]; do out="$DEST/${name}_dup$n.mp4"; n=$((n+1)); done
    mv "$f" "$out" && echo "$(date +%T) $f -> $(basename $out) dur=$dur" >> "$DEST/../watch.log"
  done
  sleep 1
done
