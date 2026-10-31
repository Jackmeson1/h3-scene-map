#!/usr/bin/env bash
# One scene worker: bring up a G4 with the self-release armed, then claim jobs from the shared queue until it is empty.
# Run several of these with different session names; they share scene_queue/ through mkdir locks.
# If the box vanishes, the lock of the running job is released (another worker may take it) and the VM is recreated, at most 3 times per worker.
# A job that fails twice is marked failed in the queue and every worker moves on.
# Do not edit this script, scene_queue.py, render_job.py or scenes.json while workers run.
# Usage: scripts/worker.sh <session> <minutes to self-release>
# Test hooks: WORKER_BRINGUP and WORKER_RUNNER replace the real bringup and job runner; WORKER_POLL sets the wait between polls.
session=$1; minutes=$2
root=$(cd "$(dirname "$0")/.." && pwd)
Q="python $root/scripts/scene_queue.py"
bringup=${WORKER_BRINGUP:-$root/scripts/worker_bringup.sh}
runner=${WORKER_RUNNER:-$root/scripts/worker_run_job.sh}
log() { echo "[$(date +%H:%M:%S)] [$session] $*"; }
export RX_SESSION=$session
boxes=0; up=0

while true; do
  if [ $up = 0 ]; then
    boxes=$((boxes + 1))
    if [ $boxes -gt 4 ]; then log "more than 3 re-creations, stopping"; exit 3; fi
    log "bringing up VM $boxes"
    if timeout "${WORKER_BRINGUP_LIMIT:-3300}" "$bringup" "$session" "$minutes"; then up=1; else log "bringup failed"; sleep "${WORKER_POLL:-30}"; continue; fi
  fi
  job=$($Q claim "$session")
  case "$job" in
    EMPTY) log "queue empty"; break ;;
    WAIT) sleep "${WORKER_POLL:-30}"; continue ;;
  esac
  log "running $job"
  out=$("$runner" "$session" "$job"); code=$?
  echo "$out" | tail -n 2 | sed "s/^/    /"
  case $code in
    0) $Q done "$job"; log "done $job" ;;
    10) $Q release "$job"; up=0; log "box gone, released $job" ;;
    *) reason=$(echo "$out" | tail -n 1); $Q fail "$job" "$reason"; log "failed $job: $reason" ;;
  esac
done
log "worker finished: $($Q status)"
