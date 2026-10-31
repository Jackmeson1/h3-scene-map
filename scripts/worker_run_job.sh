#!/usr/bin/env bash
# Run one queue job on this worker's box and pull the result straight back.
# Exit 0: done and pulled. Exit 10: the box is gone. Exit 1: the job failed; the reason is the last line printed.
# Usage: scripts/worker_run_job.sh <session> <job name>
export MSYS_NO_PATHCONV=1
session=$1; job=$2
root=$(cd "$(dirname "$0")/.." && pwd)
export RX_SESSION=$session
Q="python $(cygpath -w "$root/scripts/scene_queue.py")"  # MSYS_NO_PATHCONV is on, so Windows Python needs a Windows path
rx() { "$root/scripts/rx.sh" "$1"; }
# gone: 0 when the session is certainly absent. An unknown answer counts as not gone.
gone() { out=$(timeout 40 colab --auth adc sessions 2>/dev/null) || return 1; echo "$out" | grep -q "^\[$session\]" && return 1; echo "$out" | grep -qE "No active sessions|^\[" ; }
fail() { echo "$1"; exit 1; }

args=$($Q args "$job" | tr -d '\015')
est=$(python -c "import json;print(int(next(j['est'] for j in json.load(open(r'$(cygpath -w "$root/scene_queue/jobs.json")')) if j['name']=='$job')))" 2>/dev/null || echo 600)
for f in $($Q needs "$job" | tr -d '\015'); do  # Windows Python ends lines with CRLF
  rx "mkdir -p /root/h3/$(dirname "$f")" > /dev/null
  ok=0
  for _ in 1 2 3; do said=$(timeout 180 colab --auth adc upload -s "$session" "$(cygpath -w "$root/$f")" "/root/h3/$f" 2>&1); case "$said" in *Uploaded*) ok=1; break ;; esac; done  # the update notice can land after the result, so search all of it
  if [ $ok = 0 ]; then gone && exit 10; fail "could not upload $f: $(echo "$said" | grep -v '^$' | tail -n 1 | cut -c1-200)"; fi
done

# A backgrounded "a && b && c &" keeps a subshell holding the kernel's stdout pipe until c ends, which blocks the kernel.
started=$(rx "cd /root/h3; rm -rf scene_out/$job; setsid nohup /root/venv-comfy/bin/python scripts/render_job.py $args > /root/logs/job-$job.log 2>&1 < /dev/null &
sleep 2; echo started")
case "$started" in *started*) ;; *) gone && exit 10; fail "could not start the job" ;; esac

limit=$(( $(date +%s) + est * 3 + 900 )); silent=0
while [ "$(date +%s)" -lt "$limit" ]; do
  sleep 25
  st=$(RX_TIMEOUT=30 rx "ls /root/h3/scene_out/$job/ 2>/dev/null | grep -E '^(meta|FAILED).json'; pgrep -f '[r]ender_job.py' > /dev/null && echo RUNNING")
  case "$st" in
    *meta.json*) break ;;
    *FAILED.json*) reason=$(rx "cat /root/h3/scene_out/$job/FAILED.json" | tr -d '\n' | cut -c1-600); fail "$reason" ;;
    *RUNNING*) silent=0 ;;
    *RX_EXIT=0*) fail "the job exited without a result: $(rx "tail -n 5 /root/logs/job-$job.log" | tr '\n' ' ' | cut -c1-400)" ;;
    *) silent=$((silent + 1)); if [ $silent -ge 4 ]; then gone && exit 10; silent=0; fi ;;
  esac
done
case "$st" in *meta.json*) ;; *) gone && exit 10; fail "timed out after $(( est * 3 + 900 ))s" ;; esac

# pull: the job folder, plus the shared asset folder for jobs that make assets
rx "cd /root/h3 && tar -czf /root/preempt/pull-$job.tgz scene_out/$job \$(test -d scene_assets && echo scene_assets)" > /dev/null
tmp=$root/scene_pull_tmp/$job; rm -rf "$tmp"; mkdir -p "$tmp"
ok=0
for _ in 1 2 3; do
  timeout 400 colab --auth adc download -s "$session" "/root/preempt/pull-$job.tgz" "$(cygpath -w "$tmp/pull.tgz")" > /dev/null 2>&1 && tar -tzf "$tmp/pull.tgz" > /dev/null 2>&1 && { ok=1; break; }
done
if [ $ok = 0 ]; then gone && exit 10; fail "download failed"; fi
tar -xzf "$tmp/pull.tgz" -C "$tmp"
mkdir -p "$root/scene_results" "$root/scene_assets"
rm -rf "$root/scene_results/$job"; mv "$tmp/scene_out/$job" "$root/scene_results/$job"
if [ -d "$tmp/scene_assets" ]; then cp -n "$tmp"/scene_assets/* "$root/scene_assets/" 2>/dev/null; fi
rm -rf "$tmp"
[ -f "$root/scene_results/$job/meta.json" ] || fail "pulled folder has no meta.json"
echo "pulled $job"
exit 0
