#!/usr/bin/env bash
# The only entry point for a run of scene workers. It refuses to start anything unless the static checks and the test suite pass.
#   1. scripts/lint_ops.py            static checks on the operations scripts (known failure shapes)
#   2. the test suite                 uv run --with pytest --with numpy python -m pytest tests
#   3. the queue                      built from scenes/scenes.json if there is none yet (an existing queue is kept, so a restart resumes)
#   4. n workers (sessions la, lb, lc ...) and the budget guard
# Usage: scripts/start_workers.sh <n workers, 1 to 6> <minutes until each VM releases itself>
# Environment: BUDGET_FLOOR (default 2200 CCU): the guard stops everything below this balance.
export MSYS_NO_PATHCONV=1
n=$1; minutes=$2
root=$(cd "$(dirname "$0")/.." && pwd)
floor=${BUDGET_FLOOR:-2200}
say() { echo "[start_workers] $*"; }
die() { say "REFUSING TO START: $*"; exit 1; }

case "$n" in 1|2|3|4|5|6) ;; *) die "usage: start_workers.sh <1-6 workers> <minutes>" ;; esac
case "$minutes" in ''|*[!0-9]*) die "minutes must be a whole number" ;; esac

say "1/4 static checks"
python "$(cygpath -w "$root/scripts/lint_ops.py")"
lint=$?
[ $lint = 0 ] || die "lint_ops.py found problems (exit $lint); fix them or waive a line with '# ops-lint: ok <reason>'"

say "2/4 test suite"
(cd "$root" && uv run --with pytest --with numpy python -m pytest tests -q)
tests=$?
[ $tests = 0 ] || die "the test suite failed (exit $tests)"

names=(la lb lc ld le lf)
chosen=("${names[@]:0:$n}")
existing=$(timeout 40 colab --auth adc sessions 2>&1)
sessions_status=$?
[ $sessions_status = 0 ] || die "could not list Colab sessions (exit $sessions_status), so cannot tell whether workers already run"
for s in "${chosen[@]}"; do
  case "$existing" in *"[$s]"*) die "session $s already exists; stop it or pick fewer workers" ;; esac
done

say "3/4 queue"
if [ -f "$root/scene_queue/jobs.json" ]; then
  say "keeping the existing queue: $(python "$(cygpath -w "$root/scripts/scene_queue.py")" status)"
else
  python "$(cygpath -w "$root/scripts/scene_queue.py")" init
fi

say "4/4 workers and budget guard"
mkdir -p "$root/worker_logs"
for s in "${chosen[@]}"; do
  nohup "$root/scripts/worker.sh" "$s" "$minutes" > "$root/worker_logs/$s.log" 2>&1 < /dev/null &
  say "worker $s started"
done
nohup "$root/scripts/budget_guard.sh" "$floor" $(( minutes + 10 )) > "$root/worker_logs/guard.log" 2>&1 < /dev/null &
say "budget guard started (floor $floor CCU, $(( minutes + 10 )) minutes); logs in worker_logs/"
