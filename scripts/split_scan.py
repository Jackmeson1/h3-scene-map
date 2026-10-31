#!/usr/bin/env python3
"""Find split-screen clips: one vertical line near the centre that holds in most rows and stays put for most of the clip.

A door frame also makes a vertical line, so the report gives the score for a person to confirm by eye.
Usage: split_scan.py <folder with one sub-folder per job>
"""

import glob
import os
import subprocess
import sys

import numpy as np

W, H = 672, 384
CENTRE = 48  # columns either side of the middle
SCORE = 45.0  # median brightness step across the line; the one confirmed split reads 60+, a door frame about 30


def scan(path: str) -> tuple:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", f"fps=4,scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         check=True, capture_output=True).stdout
    video = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
    left = W // 2 - CENTRE
    steps = np.median(np.abs(video[:, :, left + 1:W // 2 + CENTRE + 1] - video[:, :, left:W // 2 + CENTRE]), axis=1)
    cols = steps.argmax(axis=1) + left
    peak = steps.max(axis=1)
    hot = peak >= SCORE
    share = float(hot.mean())
    held = float(np.median(cols[hot])) if hot.any() else -1.0
    spread = float(cols[hot].std()) if hot.any() else 0.0
    first = float(np.argmax(hot) / 4) if hot.any() else -1.0
    return round(share, 2), held, round(spread, 1), round(float(np.median(peak)), 1), first


def main() -> None:
    root = sys.argv[1]
    rows = []
    for path in sorted(glob.glob(os.path.join(root, "*", "*.mp4"))):
        if os.path.basename(path).startswith("stitched"):
            continue
        rows.append((os.path.relpath(path, root), *scan(path)))
    print(f"{len(rows)} clips; share of frames over the score, column, spread, median peak, first second")
    for r in sorted(rows, key=lambda x: -x[1]):
        if r[1] >= 0.2:
            print(r)


if __name__ == "__main__":
    main()
