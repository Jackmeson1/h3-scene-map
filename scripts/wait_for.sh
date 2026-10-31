#!/usr/bin/env bash
# Wait until a remote shell condition holds, then print the given log tail.
# Usage: scripts/wait_for.sh '<remote test>' <log path> [max_minutes]
cond=$1; logf=$2; max=${3:-30}
end=$(( $(date +%s) + max * 60 ))
while [ "$(date +%s)" -lt "$end" ]; do
  out=$(RX_TIMEOUT=30 "$(dirname "$0")/rx.sh" "if $cond; then echo COND_MET; fi; if ! pgrep -f '[p]ipeline.py|[m]ake.py' >/dev/null; then echo DRIVER_GONE; fi")
  case "$out" in
    *COND_MET*|*DRIVER_GONE*) break ;;
  esac
  sleep 20
done
RX_TIMEOUT=40 "$(dirname "$0")/rx.sh" "tail -n 14 $logf | cut -c1-400; grep -E 'it/s|s/it' /root/logs/comfyui.log | tail -n 2 | tr '\r' '\n' | tail -n 2 | cut -c1-160; nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader"
