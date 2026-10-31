#!/usr/bin/env python3
"""Objective checks on a finished run: spec, spoken lines vs script, seam jumps, loudness, contact sheets."""

import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 672, 384


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels:format=duration",
                          "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def frames(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"scale={W}:{H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float32)


def loudness(path: Path) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return float(m.group(1)) if m else float("nan")


def plain(text: str) -> str:
    return re.sub(r"[^\w]", "", text)


def seam_report(video: np.ndarray, boundaries: list[int]) -> list[dict]:
    diffs = np.abs(video[1:] - video[:-1]).mean(axis=(1, 2, 3))
    rows = []
    for b in boundaries:
        window = np.r_[diffs[max(0, b - 25):b - 2], diffs[b + 1:b + 24]]
        base = float(np.median(window))
        rows.append({"frame": b, "seam_diff": round(float(diffs[b - 1]), 2), "local_median": round(base, 2),
                     "ratio": round(float(diffs[b - 1]) / max(base, 1e-6), 2)})
    return rows


def sheet(video: np.ndarray, idx: list[int], cols: int, out: Path) -> None:
    rows = (len(idx) + cols - 1) // cols
    canvas = np.zeros((rows * H, cols * W, 3), np.uint8)
    for n, i in enumerate(idx):
        canvas[(n // cols) * H:(n // cols + 1) * H, (n % cols) * W:(n % cols + 1) * W] = video[i].astype(np.uint8)
    Image.fromarray(canvas).save(out, quality=88)


def main() -> None:
    run = Path(sys.argv[1])
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    final = run / "final.mp4"
    clips = sorted(run.glob("seg[0-9].mp4"))
    video = frames(final)

    counts, boundaries = [], []
    total = 0
    for clip in clips:
        n = int(next(s for s in probe(clip)["streams"] if s["codec_type"] == "video")["nb_frames"])
        counts.append(n)
        total += n
        boundaries.append(total)
    qc = {
        "final": probe(final),
        "frames_decoded": len(video),
        "segment_frames": counts,
        "render_seconds": report.get("render_seconds"),
        "wall_seconds": report.get("wall_seconds"),
        "seams": seam_report(video, boundaries[:-1]),
        "segment_mean_db": {c.stem: loudness(c) for c in clips},
        "speech": [],
    }
    # report.json's "speech" is the transcript the build's own gate already used, so scoring it again here proves nothing new.
    # It is labelled as such. The independent evidence is verify.json: the finished file's audio, transcribed again from scratch.
    qc["speech_is_independent"] = False
    qc["speech_note"] = "heard/match below reuse the transcript saved by the build (report.json); NOT an independent check"
    for s in report.get("speech", []):
        want, got = plain(s["text"]), plain(s["heard"])
        qc["speech"].append({"script": s["text"], "heard_saved_transcript": s["heard"],
                             "match_from_saved_transcript": round(SequenceMatcher(None, want, got).ratio(), 3),
                             "start": round(s["start"], 2), "end": round(s["end"], 2)})
    verify = run / "verify.json"
    if verify.exists():
        v = json.loads(verify.read_text(encoding="utf-8"))
        qc["independent_dialogue_check"] = {"source": v.get("source"), "passed": v.get("passed"),
                                            "segments": [{k: r[k] for k in ("seg", "heard", "match", "coverage", "problems")} for r in v["segments"]]}
    else:
        qc["independent_dialogue_check"] = "none: no verify.json in this run (older drivers do not write one)"
    (run / "qc.json").write_text(json.dumps(qc, ensure_ascii=False, indent=1), encoding="utf-8")

    sheet(video, list(range(0, len(video), 24))[:24], 4, run / "sheet_1fps.jpg")
    seam_idx = [i for b in boundaries[:-1] for i in (b - 13, b - 1, b, b + 12)]
    sheet(video, seam_idx, 4, run / "sheet_seams.jpg")
    print(json.dumps({k: v for k, v in qc.items() if k != "final"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
