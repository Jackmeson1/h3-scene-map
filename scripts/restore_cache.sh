#!/usr/bin/env bash
# Bring a fresh VM up to where the last one stopped. Weights and ComfyUI come from setup_box.sh, finished
# steps come back from cache_sync/, and make.py then skips everything already done.
# Stops with an error if the cache does not arrive intact, rather than leaving a VM that rebuilds it all.
# Usage: scripts/restore_cache.sh <session> [--no-setup]
export MSYS_NO_PATHCONV=1
session=${1:-h3}
root=$(cd "$(dirname "$0")/.." && pwd)
rx() { RX_SESSION=$session "$root/scripts/rx.sh" "$1"; }
up() { timeout 240 colab --auth adc upload -s "$session" "$(cygpath -w "$1")" "$2" 2>&1 | grep -q Uploaded; }

push() {  # a transient upload failure is normal, so each file gets a few tries
  for attempt in 1 2 3 4; do
    up "$1" "$2" && return 0
    echo "upload of $(basename "$1") failed, attempt $attempt"
  done
  echo "giving up on $1"
  exit 1
}

rx 'mkdir -p /root/h3/engine /root/h3/stories /root/h3/out /root/preempt/parts /root/logs; rm -f /root/preempt/parts/*' >/dev/null
for f in "$root"/engine/*.py "$root"/engine/*.json; do
  [ -f "$f" ] && push "$f" "/root/h3/engine/$(basename "$f")"
done
push "$root/make.py" /root/h3/make.py
for f in "$root"/stories/*.json; do push "$f" "/root/h3/stories/$(basename "$f")"; done

# A single large upload gets its connection reset, so the cache travels in pieces.
parts=$root/cache_sync/parts
rm -rf "$parts"; mkdir -p "$parts"
tar -czf - -C "$root/cache_sync" h3cache | split -b 32m - "$parts/part."
want=$(cat "$parts"/part.* | sha256sum | cut -d' ' -f1)
for p in "$parts"/part.*; do push "$p" "/root/preempt/parts/$(basename "$p")"; done
rm -rf "$parts"
got=$(rx 'cd /root/preempt && cat parts/part.* > restore.tgz.tmp && sha256sum restore.tgz.tmp | cut -d" " -f1')
case "$got" in
  *"$want"*) rx 'mv /root/preempt/restore.tgz.tmp /root/preempt/restore.tgz' >/dev/null; echo "cache arrived intact" ;;
  *) echo "cache checksum mismatch"; exit 1 ;;
esac

# The cache lives inside ComfyUI's output folder, so it goes in after the clone.
extract='mkdir -p /root/h3/ComfyUI/output && cd /root/h3/ComfyUI/output && tar -xzf /root/preempt/restore.tgz && touch /root/logs/restored'
if [ "${2:-}" = "--no-setup" ]; then
  rx "$extract && ls h3cache | wc -l"
else
  push "$root/scripts/setup_box.sh" /root/h3/setup_box.sh
  rx "setsid nohup bash -c 'bash /root/h3/setup_box.sh > /root/h3/setup.out 2>&1; $extract' > /dev/null 2>&1 < /dev/null &
sleep 1; echo setup started"
fi
