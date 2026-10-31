#!/bin/sh
# shot.sh - one call: screenshot + UI dump + fingerprints (everything needed to observe a screen)
# shot.sh - one call: screenshot + UI dump + fingerprints, everything needed to observe a screen
#
# Run on the DEVICE shell (adb shell / root or Shizuku shell / Termux).
# Output is agent-readable on purpose: one line per artifact, md5 prefix + byte size.
#
# usage:  sh scripts/shot.sh [tag]
# env:    SHOT_DIR   output directory (default /sdcard/AndroidAgentDevkit)

set -e
command -v screencap >/dev/null 2>&1 || {
  echo "ERR needs-device-shell: screencap not found (adb shell / Shizuku / Termux only)" >&2
  exit 1
}
here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)
tag="${1:-shot}"
dir="${SHOT_DIR:-/sdcard/AndroidAgentDevkit}"
mkdir -p "$dir"
img="$dir/$tag.png"
xml="$dir/$tag.xml"
screencap -p "$img"
if uiautomator dump "$xml" >/dev/null 2>&1 && [ -s "$xml" ]; then
  echo "XML $xml $(md5sum "$xml" | cut -c1-12) $(wc -c < "$xml")B"
else
  echo "WARN ui-dump-failed (self-drawn UI: Flutter/game/WebView -> read the image instead)"
fi
echo "PNG $img $(md5sum "$img" | cut -c1-12) $(wc -c < "$img")B"
