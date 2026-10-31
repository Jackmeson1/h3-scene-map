#!/usr/bin/env bash
# A G4 for a scene worker: create it, arm the self-release before anything else, then set up the author's scheme_a stack.
# Unlike bringup.sh it restores no build cache (the scene runner has none) and does not write results/preempt_deadline.txt, so workers do not trample each other.
# Every outside call has a hard timeout. Exit 0 only when setup.done exists on the box.
# Usage: scripts/worker_bringup.sh <session> <minutes to self-release>
export MSYS_NO_PATHCONV=1
session=$1; minutes=$2
root=$(cd "$(dirname "$0")/.." && pwd)
export RX_SESSION=$session
rx() { "$root/scripts/rx.sh" "$1"; }
up() { for _ in 1 2 3; do timeout 180 colab --auth adc upload -s "$session" "$(cygpath -w "$1")" "$2" 2>&1 | grep -q Uploaded && return 0; done; echo "upload of $1 failed"; return 1; }
deadline=$(( $(date +%s) + minutes * 60 ))

timeout 300 colab --auth adc new -s "$session" --gpu G4 2>&1 | grep -E "READY|rror|ailed" | cut -c1-100
rx 'mkdir -p /root/preempt /root/logs /root/h3/engine /root/h3/scripts /root/h3/scenes/v9 /root/h3/scene_assets' > /dev/null
up "$root/scripts/preempt_box.py" /root/preempt/preempt_box.py || exit 1
armed=$(rx "cd /root/preempt; setsid nohup python3 preempt_box.py $deadline > /dev/null 2>&1 < /dev/null &
sleep 2; cat /root/preempt/log")
case "$armed" in
  *armed*) echo "armed until $(date -d @"$deadline" +%H:%M:%S)" ;;
  *) echo "release daemon not armed, stopping the VM"; timeout 60 colab --auth adc stop -s "$session"; exit 1 ;;
esac

for f in "$root"/engine/*.py; do up "$f" "/root/h3/engine/$(basename "$f")" || exit 1; done
up "$root/scripts/render_job.py" /root/h3/scripts/render_job.py || exit 1
up "$root/scripts/setup_box.sh" /root/h3/setup_box.sh || exit 1
up "$root/scenes/scenes.json" /root/h3/scenes/scenes.json || exit 1
up "$root/scenes/v9/workflow_v9_final.json" /root/h3/scenes/v9/workflow_v9_final.json || exit 1
up "$root/scenes/v9/drama_config.json" /root/h3/scenes/v9/drama_config.json || exit 1
rx "cd /root/h3; setsid nohup bash setup_box.sh > /root/h3/setup.out 2>&1 < /dev/null &
sleep 1; echo setup started"

for _ in $(seq 1 120); do   # up to 40 minutes
  state=$(RX_TIMEOUT=20 rx 'test -f /root/logs/setup.done && echo READY; test -f /root/logs/setup.failed && echo FAILED')
  case "$state" in
    *READY*) echo "setup done"; exit 0 ;;
    *FAILED*) echo "setup failed"; rx 'tail -n 8 /root/logs/setup.log'; exit 1 ;;
  esac
  sleep 20
done
echo "setup did not finish in 40 minutes"; exit 1
