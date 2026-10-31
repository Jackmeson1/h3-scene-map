"""Blind transcription: what a clip's audio says, with word times, and nothing from the script passed in.

Its own module so that editing the timing code in align.py does not change the recipe of the render steps that transcribe.
"""

import subprocess
from pathlib import Path

# Part of the key of every step that transcribes (seg, verify).
WHISPER = {"model": "large-v3", "device": "cpu", "compute_type": "int8", "language": "zh", "word_timestamps": True,
           "vad_filter": True, "cpu_threads": 32}

_model = None


def transcribe(clip: Path) -> list[dict]:
    """Blind transcript with word times of whatever audio the file carries. Nothing from the script is passed in."""
    global _model
    import numpy as np
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(WHISPER["model"], device=WHISPER["device"], compute_type=WHISPER["compute_type"],
                              cpu_threads=WHISPER["cpu_threads"])
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(clip), "-vn", "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    samples = np.frombuffer(raw, np.float32)  # ComfyUI pins a PyAV that faster-whisper cannot open files with
    parts, _ = _model.transcribe(samples, language=WHISPER["language"], word_timestamps=WHISPER["word_timestamps"],
                                 vad_filter=WHISPER["vad_filter"])
    return [{"word": w.word, "start": float(w.start), "end": float(w.end)} for p in parts for w in (p.words or [])]


def heard_chars(words: list[dict]) -> list[tuple]:
    out = []
    for w in words:
        chars = [c for c in w["word"] if c.isalnum()]
        if chars:
            step = (w["end"] - w["start"]) / len(chars)
            out += [(c, w["start"] + i * step, w["start"] + (i + 1) * step) for i, c in enumerate(chars)]
    return out
