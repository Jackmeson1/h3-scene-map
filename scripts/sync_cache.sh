#!/usr/bin/env bash
# Colab GPUs are spot capacity: a VM can vanish without notice, so finished work must not live only on it.
# Pulls every finished build step that is not on this machine yet into cache_sync/.
# Stateless: it compares the box with cache_sync/, so a failed pull is simply picked up by the next run.
# Build keys are content hashes, so the same step on a fresh VM is recognised after restore_cache.sh.
# Usage: scripts/sync_cache.sh <session>
export MSYS_NO_PATHCONV=1
session=${1:-h3}
root=$(cd "$(dirname "$0")/.." && pwd)
store=$root/cache_sync
mkdir -p "$store/h3cache"
rx() { RX_SESSION=$session RX_TIMEOUT=$1 "$root/scripts/rx.sh" "$2"; }

listing=$(rx 30 'cd /root/h3/ComfyUI/output/h3cache 2>/dev/null && find . -mindepth 2 -maxdepth 2 -name done.json -printf "STEP %h\n"') || exit 1
missing=$(echo "$listing" | tr -d '\015' | sed -n 's#^STEP \./##p' | while read -r step; do
  [ -f "$store/h3cache/$step/done.json" ] || echo "h3cache/$step"
done)
if [ -z "$missing" ]; then
  echo "sync: nothing new"
  exit 0
fi

# done.json is written last, so only complete steps are listed. Live take files are not needed.
packed=$(rx 180 "cd /root/h3/ComfyUI/output && tar -czf /root/preempt/delta.tgz --exclude='take*' $(echo $missing) && echo PACKED") || exit 1
case "$packed" in *PACKED*) ;; *) echo "sync: pack failed"; exit 1 ;; esac

delta=$store/delta-$$.tgz
timeout 300 colab --auth adc download -s "$session" /root/preempt/delta.tgz "$(cygpath -w "$delta")" >/dev/null 2>&1
if tar -tzf "$delta" >/dev/null 2>&1; then  # a truncated download must not leave a done.json without its files
  tar -xzf "$delta" -C "$store"
  echo "sync: pulled $(echo "$missing" | wc -l) steps"
else
  echo "sync: download failed, will retry"
fi
rm -f "$delta"
