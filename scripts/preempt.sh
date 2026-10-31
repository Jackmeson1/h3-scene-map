#!/usr/bin/env bash
# Outside watchdog for a Colab session: keeps finished work synced, stops the session at the deadline or
# when the balance falls below the floor, and reports success only after seeing the session gone.
# Every outside call has a hard timeout, because `colab exec` can hang past its own --timeout. An unknown
# answer is treated as unknown, never as "gone".
# Usage: scripts/preempt.sh <session> <deadline epoch> <floor CCU> [grace minutes]
export MSYS_NO_PATHCONV=1
session=$1; deadline=$2; floor=$3; grace=${4:-8}
root=$(cd "$(dirname "$0")/.." && pwd)
backed=0

say() { echo "[$(date +%H:%M:%S)] $*"; }
balance() { timeout 40 colab --auth adc usage 2>/dev/null | sed -n 's/^Current balance: \([0-9.]*\).*/\1/p'; }

state() {  # up, gone or unknown
  local out
  out=$(timeout 40 colab --auth adc sessions 2>/dev/null) || { echo unknown; return; }
  if echo "$out" | grep -q "^\[$session\]"; then
    echo up
  elif echo "$out" | grep -q "No active sessions" || echo "$out" | grep -v '^\[colab\]' | grep -q '^\['; then
    echo gone
  else
    echo unknown
  fi
}

backup() {
  mkdir -p "$root/results/preempt_backup"
  say "backing up"
  RX_SESSION=$session RX_TIMEOUT=240 "$root/scripts/rx.sh" "cd /root/h3 2>/dev/null && tar -czf /root/preempt/backup.tgz --exclude='*.16k.wav' out runs 2>/dev/null; ls -la /root/preempt/backup.tgz" | tail -n 3
  timeout 400 colab --auth adc download -s "$session" /root/preempt/backup.tgz "$(cygpath -w "$root/results/preempt_backup/$session-$(date +%H%M).tgz")" 2>&1 | tail -n 1
  backed=1
}

say "watching $session until $(date -d @"$deadline" +%H:%M:%S), floor $floor"
reason=""
while [ -z "$reason" ]; do
  now=$(date +%s)
  s=$(state)
  if [ "$s" = gone ]; then
    say "session $session is gone"
    timeout 30 colab --auth adc usage 2>/dev/null | grep -E 'rate|assignments' | tr '\n' ' '; echo
    exit 0
  fi
  [ "$s" = unknown ] && say "session state unknown"
  if [ "$s" = up ]; then
    timeout 240 "$root/scripts/sync_cache.sh" "$session" | grep -v "nothing new"
    [ "$backed" = 0 ] && [ "$now" -ge $(( deadline - grace * 60 )) ] && backup
  fi
  bal=$(balance)
  if [ "$now" -ge "$deadline" ]; then
    reason="deadline"
  elif [ -n "$bal" ] && awk "BEGIN{exit !($bal < $floor)}"; then
    reason="balance $bal below floor $floor"
  else
    [ -n "$bal" ] || say "balance unavailable"
    sleep 45
  fi
done

say "preempting $session: $reason"
[ "$backed" = 1 ] || backup
for attempt in 1 2 3 4 5 6; do
  timeout 60 colab --auth adc stop -s "$session" 2>&1 | tail -n 1
  sleep 15
  s=$(state)
  if [ "$s" = gone ]; then
    say "confirmed: $session is released; $(timeout 30 colab --auth adc usage 2>/dev/null | grep -E 'rate|assignments' | tr '\n' ' ')"
    exit 0
  fi
  say "state after attempt $attempt: $s"
done
say "NOT CONFIRMED: $session may still be billing"
exit 1
