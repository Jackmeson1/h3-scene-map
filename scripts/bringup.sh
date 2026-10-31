#!/usr/bin/env bash
# A G4 that cannot outlive its budget: create it, arm the self-release before anything else, then restore.
# Refuses to go on if the release daemon is not confirmed running.
# Usage: scripts/bringup.sh <session> <minutes to deadline>
# Afterwards run scripts/preempt.sh <session> $(cat results/preempt_deadline.txt) <floor> in the background.
export MSYS_NO_PATHCONV=1
session=$1; minutes=$2
root=$(cd "$(dirname "$0")/.." && pwd)
deadline=$(( $(date +%s) + minutes * 60 ))

timeout 240 colab --auth adc new -s "$session" --gpu G4 2>&1 | grep -E "READY|rror|ailed" | cut -c1-100
RX_SESSION=$session "$root/scripts/rx.sh" 'mkdir -p /root/preempt /root/logs' >/dev/null
timeout 60 colab --auth adc upload -s "$session" "$(cygpath -w "$root/scripts/preempt_box.py")" /root/preempt/preempt_box.py 2>&1 | tail -n 1 | cut -c1-90
armed=$(RX_SESSION=$session "$root/scripts/rx.sh" "cd /root/preempt; setsid nohup python3 preempt_box.py $deadline > /dev/null 2>&1 < /dev/null &
sleep 2; cat /root/preempt/log")
case "$armed" in
  *armed*) echo "$deadline" > "$root/results/preempt_deadline.txt"; echo "armed until $(date -d @"$deadline" +%H:%M:%S)" ;;
  *) echo "release daemon not armed, stopping the VM"; timeout 60 colab --auth adc stop -s "$session"; exit 1 ;;
esac
"$root/scripts/restore_cache.sh" "$session"
