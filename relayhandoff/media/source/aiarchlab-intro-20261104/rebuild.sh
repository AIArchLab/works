#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 draw_concept.py
ffmpeg -loglevel error -y -i ui-excerpts-source.mp4 -loop 1 -i video-bg.png -filter_complex_script captions.ffscript -map '[v]' -t 21.042 -c:v libx264 -pix_fmt yuv420p -crf 20 task-continuity-ui-excerpts.mp4
ffmpeg -loglevel error -y -ss 15 -i task-continuity-ui-excerpts.mp4 -frames:v 1 poster.png
