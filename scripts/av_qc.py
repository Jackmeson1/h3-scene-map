#!/usr/bin/env python3
"""Face and voice checks on a run: who moves their mouth, does it follow the audio, does each voice stay the same person.

Runs in /root/venv-qc (mediapipe, resemblyzer), separate from ComfyUI's environment.
Usage: av_qc.py <run dir> <story json>
"""

import json
import subprocess
import sys
from pathlib import Path

import cv2
import librosa
import mediapipe as mp
import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav

FPS = 24
LIPS = (13, 14, 78, 308)  # inner upper, inner lower, left corner, right corner
YAW = (1, 234, 454)  # nose tip, face edges
MIN_FACE_FOUND = 0.90  # share of frames the speaker's face must be tracked in before a lip-sync number is reported


def face_tracks(clip: Path) -> dict:
    """Per frame, per screen side: mouth opening ratio and how frontal the face is (1 = looking at the lens)."""
    mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=False, max_num_faces=2, refine_landmarks=False,
                                           min_detection_confidence=0.3, min_tracking_confidence=0.3)
    cap = cv2.VideoCapture(str(clip))
    out = {"left": [], "right": []}
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        res = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        seen = {"left": (np.nan, np.nan), "right": (np.nan, np.nan)}
        for lm in res.multi_face_landmarks or []:
            pts = np.array([(p.x, p.y) for p in lm.landmark])
            side = "left" if pts[1, 0] < 0.5 else "right"
            gap = np.linalg.norm(pts[LIPS[0]] - pts[LIPS[1]])
            width = np.linalg.norm(pts[LIPS[2]] - pts[LIPS[3]]) + 1e-6
            nose, a, b = pts[YAW[0]], pts[YAW[1]], pts[YAW[2]]
            da, db = abs(nose[0] - a[0]), abs(nose[0] - b[0])
            seen[side] = (gap / width, min(da, db) / (max(da, db) + 1e-6))
        for side in out:
            out[side].append(seen[side])
    cap.release()
    return {k: np.array(v) for k, v in out.items()}


def loudness_track(clip: Path, n: int) -> np.ndarray:
    y, sr = librosa.load(str(clip), sr=16000, mono=True)
    hop = sr // FPS
    rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    return rms[:n]


def lag_frames(mouth: np.ndarray, sound: np.ndarray, reach: int = 8) -> tuple[int, float]:
    n = min(len(mouth), len(sound))
    m = np.nan_to_num(mouth[:n], nan=np.nanmedian(mouth))
    s = sound[:n]
    best = (0, -2.0)
    for lag in range(-reach, reach + 1):
        a, b = (m[lag:], s[:n - lag]) if lag >= 0 else (m[:n + lag], s[-lag:])
        if a.std() > 0 and b.std() > 0:
            r = float(np.corrcoef(a, b)[0, 1])
            if r > best[1]:
                best = (lag, r)
    return best


def main() -> None:
    run, story = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    encoder = VoiceEncoder("cpu", verbose=False)
    rows, voices = [], {}
    for i, seg in enumerate(story["segments"], start=1):
        clip = run / f"seg{i}.mp4"
        tracks = face_tracks(clip)
        n = len(tracks["left"])
        sound = loudness_track(clip, n)
        speaker, listener = seg["speaker"], "right" if seg["speaker"] == "left" else "left"
        s_mouth, l_mouth = tracks[speaker][:, 0], tracks[listener][:, 0]
        found = {k: round(float(np.mean(~np.isnan(v[:, 0]))), 2) for k, v in tracks.items()}
        scorable = found[speaker] >= MIN_FACE_FOUND  # with fewer tracked frames the median-filled signal says nothing about the lips
        lag, corr = lag_frames(s_mouth, sound) if scorable else (None, None)
        rows.append({
            "seg": i, "speaker": speaker,
            "face_found": found,
            "scorable": scorable,
            "unscorable_reason": None if scorable else f"speaker face found in {found[speaker]:.0%} of frames, under {MIN_FACE_FOUND:.0%}",
            "speaker_mouth_std": round(float(np.nanstd(s_mouth)), 4),
            "listener_mouth_std": round(float(np.nanstd(l_mouth)), 4),
            "mouth_sound_corr": None if corr is None else round(corr, 3),
            "best_lag_ms": None if lag is None else round(lag * 1000 / FPS),
            "most_frontal": {k: round(float(np.nanpercentile(v[:, 1], 95)), 2) for k, v in tracks.items()},
        })
        voices.setdefault(speaker, []).append(encoder.embed_utterance(preprocess_wav(str(run / f"seg{i}.16k.wav"))))

    pairs = {}
    for who, embs in voices.items():
        pairs[f"same_{who}"] = [round(float(np.dot(embs[a], embs[b])), 3) for a in range(len(embs)) for b in range(a + 1, len(embs))]
    keys = list(voices)
    if len(keys) == 2:
        pairs["cross"] = [round(float(np.dot(a, b)), 3) for a in voices[keys[0]] for b in voices[keys[1]]]
    result = {"segments": rows, "voice_similarity": pairs}
    (run / "av_qc.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
