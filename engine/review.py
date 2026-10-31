"""What decides whether a take is kept. Every check here runs on the clean clip, before overlays and before the
next segment builds on it.

ALL THRESHOLDS BELOW ARE PROVISIONAL. They were set from a handful of takes (two stories, ten segments) and are
not validated across other lighting, scenes, speakers or Whisper versions. Where the data cannot separate good from
bad the report says so; nothing here was loosened to make a render pass.
"""

import json
import subprocess
from pathlib import Path

import numpy as np

from .script import MIN_CLOSING_SILENCE, spoken  # noqa: F401
from .transcribe import heard_chars

MAX_TRIES = 3
SEED_STRIDE = 100  # retake n of a segment uses seed + SEED_STRIDE * n

JUMP_DIFF = 15.0  # mean 8-bit change between frames; a hard cut measures ~49, normal motion stays under 7

# Dialogue. SequenceMatcher ratio of the script against a blind transcript, plus the share of script characters found.
# 0.8 accepts the 师傅/师父 homophone (7 of 8 characters, ratio 0.875) and rejects 4 of 8 characters (ratio 0.667).
MIN_MATCH = 0.8
MIN_COVER = 0.8
NEGATIONS = "不没别无未勿"  # a dropped or added negation reverses the meaning and still scores ~0.94 on ratio alone

# Framing drift. 168x96 RGB against the fixed two-shot, sampled at 2 Hz, reject on three consecutive samples whose mean
# absolute difference is above 35 (of 255). From the noodle data: ordinary performance stays below ~32, the push-in reads
# 39-54.
DRIFT_SIZE = (168, 96)
DRIFT_HZ = 2.0
DRIFT_DIFF = 35.0
DRIFT_RUN = 3

# The take must stay quiet at the end: the next clip is conditioned on its closing frames. The floor itself (0.5 s) lives in
# script.py so that clip_length, the prompt and this gate use one number; the model delivered 0.43 to 2.3 s in the kept data.

GRID = {"every": 0.5, "cols": 4}

# Establishing shot: no hard cut, the last 1.5 s stable against the clip's own final frame (same drift measure and threshold as above),
# and a face found on each side of the frame in at least 2 of 3 frames taken near the end. PROVISIONAL, like everything here.
ESTABLISH_STABLE_SECONDS = 1.5
ESTABLISH_FACE_OFFSETS = (1.0, 0.7, 0.4)  # seconds before the clip end; the last is the frame the two-shot is cut from
ESTABLISH_FACES_NEEDED = 2
FACE_PYTHON = "/root/venv-qc/bin/python"  # mediapipe lives here, not in ComfyUI's environment
FACES_SCRIPT = Path(__file__).with_name("faces.py")


class AcceptanceError(RuntimeError):
    """A take, or the finished file, did not pass its gate and no retakes are left."""

    def __init__(self, message: str, takes: list = None):
        super().__init__(message)
        self.takes = takes or []


def gate_settings() -> dict:
    """Everything above, for the key of every step that judges takes."""
    return {"max_tries": MAX_TRIES, "seed_stride": SEED_STRIDE, "jump_diff": JUMP_DIFF, "min_match": MIN_MATCH,
            "min_cover": MIN_COVER, "negations": NEGATIONS, "drift": [DRIFT_SIZE, DRIFT_HZ, DRIFT_DIFF, DRIFT_RUN],
            "min_closing_silence": MIN_CLOSING_SILENCE, "grid": GRID,
            "establish": [ESTABLISH_STABLE_SECONDS, ESTABLISH_FACE_OFFSETS, ESTABLISH_FACES_NEEDED]}


# ---- picture -------------------------------------------------------------------------------------------------

def jump_frames(clip: Path) -> list[int]:
    """Frames where the picture jumps: a hard cut the model made inside a clip."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(clip), "-vf", "scale=168:96,format=gray", "-f", "rawvideo", "-"],
                         check=True, capture_output=True).stdout
    video = np.frombuffer(raw, np.uint8).reshape(-1, 96, 168).astype(np.float32)
    diffs = np.abs(video[1:] - video[:-1]).mean(axis=(1, 2))
    return [int(i) + 1 for i in np.flatnonzero(diffs > JUMP_DIFF)]


def _rgb(args: list[str]) -> np.ndarray:
    w, h = DRIFT_SIZE
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", *args, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32)


def sample_clip(clip: Path) -> np.ndarray:
    """The clip at DRIFT_HZ, 168x96 RGB, (n, 96, 168, 3)."""
    w, h = DRIFT_SIZE
    return _rgb(["-i", str(clip), "-vf", f"fps={DRIFT_HZ},scale={w}:{h}"])


def load_reference(image: Path) -> np.ndarray:
    w, h = DRIFT_SIZE
    return _rgb(["-i", str(image), "-vf", f"scale={w}:{h}", "-frames:v", "1"])[0]


def reference_from_clip(clip: Path, at: float) -> np.ndarray:
    """One frame of a clip at `at` seconds."""
    w, h = DRIFT_SIZE
    return _rgb(["-ss", f"{max(at, 0.0):.3f}", "-i", str(clip), "-vf", f"scale={w}:{h}", "-frames:v", "1"])[0]


def drift_diffs(samples: np.ndarray, reference: np.ndarray, mask_bottom: float = 0.0) -> list[float]:
    """Mean absolute difference (0-255) of every sample from the reference. mask_bottom ignores that fraction of rows at
    the bottom, for files that already carry burned-in captions. A clean clip is judged with mask_bottom = 0."""
    rows = int(round(samples.shape[1] * (1.0 - mask_bottom)))
    return [float(np.abs(s[:rows] - reference[:rows]).mean()) for s in samples]


def drift_verdict(diffs: list[float]) -> list[str]:
    run = 0
    for i, d in enumerate(diffs):
        run = run + 1 if d > DRIFT_DIFF else 0
        if run >= DRIFT_RUN:
            first = i - DRIFT_RUN + 1
            return [f"framing drifted from the two-shot: {DRIFT_RUN} samples in a row above {DRIFT_DIFF:g}/255 from {first / DRIFT_HZ:.1f}s "
                    f"(values {[round(x, 1) for x in diffs[first:i + 1]]})"]
    return []


# ---- speech --------------------------------------------------------------------------------------------------

def negation_counts(line: str, heard: str) -> tuple[int, int]:
    return sum(spoken(line).count(c) for c in NEGATIONS), sum(heard.count(c) for c in NEGATIONS)


def dialogue_scores(line: str, words: list[dict]) -> dict:
    from difflib import SequenceMatcher
    want = "".join(c for c in spoken(line) if c.isalnum())
    got = "".join(c for c, _, _ in heard_chars(words))
    blocks = SequenceMatcher(None, want, got, autojunk=False)
    matched = sum(b.size for b in blocks.get_matching_blocks())
    want_neg, got_neg = negation_counts(line, got)
    return {"match": round(blocks.ratio(), 3), "coverage": round(matched / max(len(want), 1), 3),
            "negations_script": want_neg, "negations_heard": got_neg}


def dialogue_verdict(line: str, words: list[dict]) -> tuple[dict, list[str]]:
    s = dialogue_scores(line, words)
    problems = []
    if s["match"] < MIN_MATCH:
        problems.append(f"spoken line matches the script only {s['match']:.2f} (needs {MIN_MATCH})")
    if s["coverage"] < MIN_COVER:
        problems.append(f"only {s['coverage']:.2f} of the script characters were heard (needs {MIN_COVER})")
    if s["negations_script"] != s["negations_heard"]:
        problems.append(f"negation characters differ: script has {s['negations_script']}, transcript has {s['negations_heard']}")
    return s, problems


def closing_silence(words: list[dict], duration: float) -> float:
    return duration - max((w["end"] for w in words), default=0.0)


def silence_verdict(words: list[dict], duration: float) -> list[str]:
    gap = closing_silence(words, duration)
    if gap < MIN_CLOSING_SILENCE:
        return [f"speech ends {gap:.2f}s before the clip end, needs {MIN_CLOSING_SILENCE}s of closed-mouth silence"]
    return []


def judge_take(line: str, words: list[dict], jumps: list[int], drift: list[float], duration: float) -> tuple[dict, list[str]]:
    scores, problems = dialogue_verdict(line, words)
    if jumps:
        problems.insert(0, f"cut inside the clip at frames {jumps}")
    problems += drift_verdict(drift)
    problems += silence_verdict(words, duration)
    return scores, problems


# ---- establishing shot ---------------------------------------------------------------------------------------

def find_faces(images: list, python: str = FACE_PYTHON, script: Path = FACES_SCRIPT):
    """One {"left", "right", "faces"} per image, from mediapipe run in its own interpreter. None when that cannot be done for any reason."""
    try:
        out = subprocess.run([python, str(script), *[str(i) for i in images]], capture_output=True, text=True, timeout=300, check=True).stdout
        result = json.loads(out.strip().splitlines()[-1])
    except Exception:  # missing interpreter, missing mediapipe, crash, bad output: all the same answer, "could not judge"
        return None
    return result if isinstance(result, list) and len(result) == len(images) else None


def faces_verdict(results, needed: int = ESTABLISH_FACES_NEEDED) -> list[str]:
    """A face on each side in at least `needed` of the frames. If the faces could not be judged at all that is a failed check, not a pass."""
    if not isinstance(results, list) or not results or not all(isinstance(r, dict) and "left" in r and "right" in r for r in results):
        return ["faces could not be judged (no usable result from the face check): failing closed"]
    problems = []
    for side in ("left", "right"):
        seen = sum(1 for r in results if r[side])
        if seen < needed:
            problems.append(f"no face on the {side} of the frame near the end ({seen} of {len(results)} frames, needs {needed})")
    return problems


def establish_problems(jumps: list[int], stable_diffs: list[float], faces) -> list[str]:
    problems = []
    if jumps:
        problems.append(f"cut inside the clip at frames {jumps}")
    if len(stable_diffs) < DRIFT_RUN:
        problems.append("too few samples in the closing window to judge stability: failing closed")
    else:
        problems += [p.replace("framing drifted from the two-shot", "closing frames are not stable") for p in drift_verdict(stable_diffs)]
    problems += faces_verdict(faces)
    return problems


# ---- retakes -------------------------------------------------------------------------------------------------

def run_takes(attempt, max_tries: int = MAX_TRIES) -> tuple[list[dict], dict]:
    """attempt(n) renders and judges take n and returns {"problems": [...], ...}. The first clean take wins.
    When every take is rejected this raises AcceptanceError carrying all of them; the caller keeps them on disk."""
    takes = []
    for n in range(max_tries):
        record = attempt(n)
        takes.append(record)
        if not record["problems"]:
            return takes, record
    raise AcceptanceError(f"all {max_tries} takes were rejected: " + "; ".join(f"take {i}: {t['problems']}" for i, t in enumerate(takes)), takes)


def frame_grid(clip: Path, out: Path, every: float = None, cols: int = None) -> None:
    """A continuous grid for looking at, because the checks above cannot see everything."""
    every, cols = every or GRID["every"], cols or GRID["cols"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-vf",
                    f"fps={1 / every},scale=480:-1,tile={cols}x8", "-frames:v", "1", "-q:v", "4", str(out)], check=True)
