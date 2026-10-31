#!/usr/bin/env python3
"""Runs on the VM, detached from every agent: at the deadline the VM releases itself.

The deadline is fixed at launch, so nothing a job writes to disk can move it. To extend, kill this
process and start a new one. Release goes through the same endpoint as google.colab.runtime.unassign.

Usage: preempt_box.py <deadline epoch seconds>
"""

import http.client
import os
import sys
import time

ADDR = os.environ.get("TBE_RUNTIME_ADDR", "172.28.0.1:8011")
LOG = "/root/preempt/log"


def log(msg: str) -> None:
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def release() -> int:
    conn = http.client.HTTPConnection(ADDR, timeout=15)
    conn.request("POST", "/unassign")
    return conn.getresponse().status


def main() -> None:
    deadline = float(sys.argv[1])
    log(f"armed, {deadline - time.time():.0f}s to deadline")
    while time.time() < deadline:
        time.sleep(min(20.0, max(0.5, deadline - time.time())))
    while True:  # keeps asking until the VM is gone
        try:
            log(f"deadline reached, unassign -> {release()}")
        except Exception as exc:
            log(f"unassign failed: {exc}")
        time.sleep(30)


if __name__ == "__main__":
    main()
