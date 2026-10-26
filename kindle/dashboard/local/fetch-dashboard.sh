#!/usr/bin/env sh
# Download the latest pre-rotated dashboard image to "$1".
"$(dirname "$0")/../xh" -d -q -o "$1" get \
  https://raw.githubusercontent.com/MaximHarper/kindle-weather/dashboard/dashboard.png
