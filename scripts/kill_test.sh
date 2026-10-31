#!/usr/bin/env bash
# Reclaim test: once segment 2 has finished, wait, then release the VM with no warning, mid-render.
# Usage: scripts/kill_test.sh <seconds after seg2>
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."
while true; do
  out=$(RX_TIMEOUT=20 scripts/rx.sh "grep -c 'seg2 take' /root/logs/kill_test.log")
  case "$out" in *1*|*2*|*3*) break ;; esac
  sleep 15
done
echo "seg2 finished at $(date +%H:%M:%S)"
sleep "$1"
RX_TIMEOUT=20 scripts/rx.sh "tail -n 3 /root/logs/kill_test.log | cut -c1-100; python3 -c \"import http.client,os; c=http.client.HTTPConnection(os.environ['TBE_RUNTIME_ADDR'],timeout=15); c.request('POST','/unassign'); print('unassign', c.getresponse().status)\"" 
echo "killed at $(date +%H:%M:%S)"
