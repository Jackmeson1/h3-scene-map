#!/usr/bin/env bash
export MSYS_NO_PATHCONV=1
# Run one shell command on the h3 Colab box through its kernel and print the output.
# colab exec can hang past its own --timeout, so the outer timeout is the real limit.
# Usage: scripts/rx.sh 'nvidia-smi'    RX_TIMEOUT=120 scripts/rx.sh '...'
tmp=$(mktemp --suffix=.py)
python -I - "$*" > "$tmp" <<'EOF'
import json, sys
print("import subprocess")
print("p = subprocess.run(%s, shell=True, executable='/bin/bash', capture_output=True, text=True)" % json.dumps(sys.argv[1]))
print("print(p.stdout[-8000:]); print(p.stderr[-2500:]); print(f'RX_EXIT={p.returncode}')")
EOF
timeout $(( ${RX_TIMEOUT:-60} + 20 )) colab --auth adc exec -s "${RX_SESSION:-h3}" -f "$(cygpath -w "$tmp")" --timeout "${RX_TIMEOUT:-60}" 2>&1 \
  | grep -vE "^\[colab\] (A new version|Run 'colab update'|To silence)"
rm -f "$tmp"
