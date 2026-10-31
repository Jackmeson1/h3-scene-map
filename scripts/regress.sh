#!/usr/bin/env bash
# Regression on a freshly built VM: wait for setup, pin the engine, print the plan, build a story unattended.
# Usage: scripts/regress.sh <session> <story name> <run name>
export MSYS_NO_PATHCONV=1
session=$1; story=$2; name=$3
root=$(cd "$(dirname "$0")/.." && pwd)
rx() { RX_SESSION=$session "$root/scripts/rx.sh" "$1"; }

for _ in $(seq 1 40); do
  state=$(RX_TIMEOUT=15 rx 'test -f /root/logs/restored && echo READY; test -f /root/logs/setup.failed && echo FAILED')
  case "$state" in *READY*|*FAILED*) break ;; esac
  sleep 12
done
case "$state" in
  *READY*) ;;
  *) echo "setup did not finish: $state"; rx 'cat /root/logs/setup.log; tail -n 5 /root/h3/setup.out'; exit 1 ;;
esac
rx 'cat /root/logs/setup.log; fc-list | grep -c "Noto Sans CJK"' | grep -v '^$'

RX_TIMEOUT=60 rx 'cd /root/h3 && /root/venv-comfy/bin/python make.py --pin-engine 2>&1 | tail -n 4; ls -la engine/engine.lock.json' | grep -v '^$'
timeout 60 colab --auth adc download -s "$session" /root/h3/engine/engine.lock.json "$(cygpath -w "$root/engine/engine.lock.json")" 2>&1 | tail -n 1 | cut -c1-90
RX_TIMEOUT=60 rx "cd /root/h3 && /root/venv-comfy/bin/python make.py stories/$story.json --plan 2>&1 | tail -n 22" | grep -v '^$'
rx "cd /root/h3; setsid nohup /root/venv-comfy/bin/python make.py stories/$story.json --name $name > /root/logs/$name.log 2>&1 < /dev/null &
sleep 2; echo started $name"
