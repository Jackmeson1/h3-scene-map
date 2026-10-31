#!/usr/bin/env bash
# Reuse the worker's VM if it is still up, otherwise build a new one. Lets workers restart without paying for setup again.
# Usage: scripts/worker_bringup_once.sh <session> <minutes>
root=$(cd "$(dirname "$0")/.." && pwd)
if timeout 40 colab --auth adc sessions 2>/dev/null | grep -q "^\[$1\]"; then
  echo "$1 is up, reusing it"
  exit 0
fi
exec "$root/scripts/worker_bringup.sh" "$1" "$2"
