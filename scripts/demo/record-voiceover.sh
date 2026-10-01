#!/usr/bin/env bash
# Record a voiceover over an already-rendered demo clip, then mux the two.
#
#   scripts/demo/record-voiceover.sh [video] [mic-name-substring]
#
# Opens the video in QuickTime, counts down, starts playback and mic capture
# together, stops when you press Enter, and writes <video>-voiced.mp4 beside the
# input. Re-run to retake. With no mic named it takes the first audio input
# ffmpeg lists, which is usually the built-in microphone.
# If a take peaks below about -12 dB, turn the input gain up and go again.
set -euo pipefail

VIDEO="${1:-scripts/demo/out/agent-session.mp4}"
MIC="${2:-}"
OUT="${VIDEO%.mp4}-voiced.mp4"
WAV="${VIDEO%.mp4}-voice.wav"

[ -f "$VIDEO" ] || { echo "no such video: $VIDEO"; exit 1; }

# Resolve the avfoundation audio device index, by name substring or first listed.
# ffmpeg exits non-zero after listing devices; that is expected, hence the `|| true`.
DEVICES=$( (ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 || true) \
  | sed -n '/audio devices/,$p' | grep -E '^\[[^]]+\] \[[0-9]+\]' )
if [ -n "$MIC" ]; then
  DEVICES=$(printf '%s\n' "$DEVICES" | { grep -i "$MIC" || true; })
fi
DEV=$(printf '%s\n' "$DEVICES" | head -1 | sed -E 's/.*\[([0-9]+)\].*/\1/')
[ -n "$DEV" ] || { echo "no audio input${MIC:+ matching '$MIC'} found"; exit 1; }

DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
MAXLEN=1800  # hard stop at 30 min; the normal stop is pressing Enter
ABS=$(cd "$(dirname "$VIDEO")" && pwd)/$(basename "$VIDEO")

echo "video: $VIDEO (${DUR%.*}s)   mic: device $DEV"
open -a "QuickTime Player" "$ABS"
sleep 2
for n in 3 2 1; do echo "  starting in $n"; sleep 1; done

osascript -e 'tell application "QuickTime Player" to play document 1' >/dev/null
echo "  RECORDING. Talk over the video. Press ENTER when you have finished speaking."
echo "  (keep going past the end of the video if you need to; the last frame is held)"
ffmpeg -hide_banner -loglevel error -y -nostdin \
  -f avfoundation -i ":$DEV" -t "$MAXLEN" -ac 1 -ar 48000 "$WAV" &
FF=$!
read -r _
kill -INT "$FF" 2>/dev/null || true
wait "$FF" 2>/dev/null || true

osascript -e 'tell application "QuickTime Player" to close document 1 saving no' >/dev/null 2>&1 || true
ADUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$WAV")
ffmpeg -hide_banner -i "$WAV" -af volumedetect -f null - 2>&1 | grep -E "max_volume" | sed 's/.*\]/  level:/'
echo "  voice ${ADUR%.*}s, video ${DUR%.*}s. muxing (video held on the last frame if the voice runs longer)..."
ffmpeg -hide_banner -loglevel error -y -i "$VIDEO" -i "$WAV" \
  -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=600[v]" -map "[v]" -map 1:a \
  -c:v libx264 -pix_fmt yuv420p -crf 20 -c:a aac -b:a 160k -shortest "$OUT"
echo "done: $OUT"
echo "the raw voice track is kept at $WAV, in case the sync needs nudging"
