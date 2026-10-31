#!/bin/sh
# screen.sh - cache the device resolution for shrink.py / tapcalc.py
# screen.sh - cache the device resolution into scripts/.screen.txt
#
# Run on the DEVICE shell (adb shell / root or Shizuku shell / Termux).
# Run on the DEVICE shell: adb shell, a root/Shizuku shell, or Termux.
# No shell access on the phone? Skip it and pass --screen WxH or $TOKEN_TOOLS_SCREEN.
#
# usage:  sh scripts/screen.sh [out-dir]

set -e
here=$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)
out="${1:-$here}"
size=$(wm size 2>/dev/null | awk '/Override size/ {print $NF} /Physical size/ {print $NF}' | tail -1)
if [ -z "$size" ]; then
  echo "ERR wm-size-failed: no shell access? pass --screen WxH instead" >&2
  exit 1
fi
dpi=$(wm density 2>/dev/null | awk '/Override density/ {print $NF} /Physical density/ {print $NF}' | tail -1)
printf '%s  # %s dpi\n' "$size" "$dpi" > "$out/.screen.txt"
echo "SCREEN $size dpi=$dpi -> $out/.screen.txt"
