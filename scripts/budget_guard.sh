#!/usr/bin/env bash
# The ceiling over all workers. A worker recreates its VM after a reclaim, so each VM's own deadline does not bound the
# whole run. At the balance floor or the time limit this stops every worker, then every session, and confirms it.
# Exits on its own once the workers have finished and no session is left.
# Usage: scripts/budget_guard.sh <floor CCU> <max minutes>
floor=$1; end=$(( $(date +%s) + $2 * 60 ))
say() { echo "[$(date +%H:%M:%S)] $*"; }
workers() { powershell.exe -NoProfile -Command "(Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'scripts/worker\.sh' } | Measure-Object).Count" 2>/dev/null | tr -d '\015 '; }
sessions() { timeout 40 colab --auth adc sessions 2>/dev/null | grep -v '^\[colab\]' | sed -n 's/^\[\([^]]*\)\].*/\1/p'; }
balance() { timeout 40 colab --auth adc usage 2>/dev/null | sed -n 's/^Current balance: \([0-9.]*\).*/\1/p'; }

say "guarding: floor $floor, until $(date -d @"$end" +%H:%M:%S)"
sleep 120
reason=""
while [ -z "$reason" ]; do
  bal=$(balance)
  if [ "$(date +%s)" -ge "$end" ]; then
    reason="time limit"
  elif [ -n "$bal" ] && awk "BEGIN{exit !($bal < $floor)}"; then
    reason="balance $bal below floor $floor"
  elif [ "$(workers)" = "0" ] && [ -z "$(sessions)" ]; then
    say "workers finished and no session left; balance $bal"
    exit 0
  fi
  [ -z "$reason" ] && sleep 60
done

say "stopping everything: $reason"
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -match 'scripts/lan[e]' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>/dev/null
for attempt in 1 2 3 4 5; do
  left=$(sessions)
  [ -z "$left" ] && { say "confirmed: no session left; $(timeout 30 colab --auth adc usage 2>/dev/null | grep -E 'rate|assign' | tr '\n' ' ')"; exit 0; }
  for s in $left; do timeout 60 colab --auth adc stop -s "$s" 2>&1 | tail -n 1 | cut -c1-80; done
  sleep 15
done
say "NOT CONFIRMED: sessions may still be billing: $(sessions | tr '\n' ' ')"
exit 1
