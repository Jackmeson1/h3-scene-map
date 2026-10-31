#!/usr/bin/env python3
"""story.json in, finished video out. Reruns only what the story change, or a change to the engine's code, touches.

python make.py story.json --name v1                         build
python make.py story.json --plan                            what would run and what it would cost; flags invalid results
python make.py story.json --name v2 --set segments.3.line=… one change, everything else reused
python make.py --pin-engine                                 on a known-good box: record the weight sizes ENGINE is checked against

Exit codes: 0 done, 2 story rejected by lint, 3 a gate failed (retakes exhausted, or the finished file failed its independent
check; nothing is published), 4 the installed engine is not the pinned one, 1 anything else.
"""

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from engine.build import Build, Step, read_marker
from engine.comfy import COMFY, ENGINE, clip_graph, pin_engine, saved_mp4, start_comfy, submit, to_input, verify_engine
from engine.review import (AcceptanceError, DRIFT_HZ, ESTABLISH_FACE_OFFSETS, ESTABLISH_STABLE_SECONDS, MAX_TRIES, SEED_STRIDE, dialogue_verdict,
                           drift_diffs, establish_problems, find_faces, frame_grid, gate_settings, judge_take, jump_frames, load_reference,
                           reference_from_clip, run_takes, sample_clip)
from engine.script import CAST_LENGTH, FPS, SIDES, clip_length, spoken
from engine.story import lint, load
from engine.transcribe import WHISPER
from engine.prompts import cast_prompt, establish_prompt, segment_prompt

CACHE = COMFY / "output" / "h3cache"
OUT = Path("/root/h3/out")
FONT = "Noto Sans CJK SC"

# Everything below that a step does is a literal here, so it is part of that step's key.
PLATE_TIME = 4.8  # default second of the casting clip kept as the portrait
ESTABLISH_LENGTH = 124  # frames of the silent establishing two-shot
TWO_SHOT_BACKOFF = 0.4  # the two-shot is the establishing clip's frame this far before its end
VOICE_FILTER = "aresample=32000,pan=stereo|c0=c0|c1=c0"
VOICE_CODEC = "pcm_s16le"
ENCODE = {"vcodec": "libx264", "crf": 15, "pix_fmt": "yuv420p", "acodec": "aac", "ab": "192k", "ar": 32000}
CONCAT = "concat-filter, audio padded or trimmed to each clip's video length"


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def video_frames(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip().rstrip(",")
    return int(out)


def video_seconds(path: Path) -> float:
    """The picture's length, from its frames. The container duration also counts any longer audio track."""
    return video_frames(path) / FPS


def comfy_prefix(step: Step, leaf: str = "") -> str:
    return f"h3cache/{step.dir.name}" + (f"/{leaf}" if leaf else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("story", nargs="?")
    ap.add_argument("--name", default=None)
    ap.add_argument("--set", action="append", default=[], dest="sets")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--pin-engine", action="store_true")
    args = ap.parse_args()

    if args.pin_engine:
        print(json.dumps(pin_engine(), indent=1))
        return 0
    if not args.story:
        ap.error("a story file is required")
    story = load(args.story, args.sets)
    problems = lint(story)
    if problems:
        print("story rejected before any render:\n  " + "\n  ".join(problems))
        return 2
    b = Build(CACHE, plan_only=args.plan)
    if not args.plan:
        try:
            verify_engine()  # before any GPU work
        except RuntimeError as exc:
            print(exc)
            return 4
        CACHE.mkdir(parents=True, exist_ok=True)
        start_comfy()
    try:
        return build(story, args, b)
    except AcceptanceError as exc:
        print(b.summary())
        print(f"BUILD FAILED, nothing published: {exc}")
        return 3


def build(story: dict, args, b: Build) -> int:
    plates, voices, casts = {}, {}, {}
    plate_time = story.get("plate_time", PLATE_TIME)
    for offset, side in enumerate(SIDES, start=1):
        who = story["characters"][side]
        prompt = cast_prompt(story, who)
        seed = story["seed"] + offset

        def cast(step: Step, prompt=prompt, seed=seed) -> None:
            entry = submit(clip_graph(prompt, CAST_LENGTH, seed, comfy_prefix(step, "clip")), step.name)
            shutil.copy2(saved_mp4(entry), step.dir / "clip.mp4")

        casts[side] = b.step(f"cast_{side}", {"engine": ENGINE, "prompt": prompt, "seed": seed, "length": CAST_LENGTH}, [], cast,
                             outputs=["clip.mp4"], recipe=["comfy.py", "prompts.py", "script.py"], estimate=150, gpu=True)

        def plate(step: Step, source=casts[side]) -> None:
            ffmpeg("-ss", str(plate_time), "-i", str(source.dir / "clip.mp4"), "-frames:v", "1", str(step.dir / "plate.png"))

        def voice(step: Step, source=casts[side]) -> None:
            ffmpeg("-i", str(source.dir / "clip.mp4"), "-vn", "-af", VOICE_FILTER, "-c:a", VOICE_CODEC, str(step.dir / "voice.wav"))

        plates[side] = b.step(f"plate_{side}", {"time": plate_time, "rule": "one frame at time, ffmpeg -ss before -i, png"}, [casts[side]], plate,
                              outputs=["plate.png"])
        voices[side] = b.step(f"voice_{side}", {"filter": VOICE_FILTER, "codec": VOICE_CODEC}, [casts[side]], voice, outputs=["voice.wav"])

    est_prompt = establish_prompt(story, ESTABLISH_LENGTH)
    est_seed = story["seed"] + 50

    def establish(step: Step) -> dict:
        """A silent two-shot from the two portraits. Judged like a segment take: no cut, a stable closing 1.5 s, a face on each side."""
        images = [to_input(plates[s].dir / "plate.png") for s in SIDES]

        def attempt(n: int) -> dict:
            graph = clip_graph(est_prompt, ESTABLISH_LENGTH, est_seed + SEED_STRIDE * n, comfy_prefix(step, f"take{n}"), images=images)
            take = saved_mp4(submit(graph, f"establish take {n}"))
            seconds = video_seconds(take)
            jumps = jump_frames(take)
            samples = sample_clip(take)
            start = max(0, math.ceil((seconds - ESTABLISH_STABLE_SECONDS) * DRIFT_HZ - 1e-6))
            stable = drift_diffs(samples[start:], reference_from_clip(take, seconds - 0.05))
            pngs = []
            for k, off in enumerate(ESTABLISH_FACE_OFFSETS):
                png = step.dir / f"faces_take{n}_{k}.png"
                ffmpeg("-ss", f"{seconds - off:.3f}", "-i", str(take), "-frames:v", "1", str(png))
                pngs.append(png)
            faces = find_faces(pngs)
            bad = establish_problems(jumps, stable, faces)
            print(f"establish take {n}: {bad or 'accepted'}", flush=True)
            return {"seed": est_seed + SEED_STRIDE * n, "file": str(take), "jumps": jumps, "stable_diffs": [round(d, 1) for d in stable],
                    "faces": faces, "problems": bad}

        try:
            takes, kept = run_takes(attempt, MAX_TRIES)
        except AcceptanceError as exc:
            (step.dir / "rejected.json").write_text(json.dumps(exc.takes, ensure_ascii=False, indent=1), encoding="utf-8")
            raise
        shutil.copy2(kept["file"], step.dir / "clip.mp4")
        (step.dir / "faces.json").write_text(json.dumps(kept["faces"]), encoding="utf-8")
        frame_grid(step.dir / "clip.mp4", step.dir / "grid.jpg")
        return {"takes": takes}

    establish_step = b.step("establish", {"engine": ENGINE, "prompt": est_prompt, "length": ESTABLISH_LENGTH, "seed": est_seed, "gates": gate_settings(),
                                          "audio": "none"},
                            [plates["left"], plates["right"]], establish, outputs=["clip.mp4", "faces.json", "grid.jpg"],
                            recipe=["comfy.py", "prompts.py", "review.py", "script.py", "faces.py"], estimate=165, gpu=True)

    def plate_two(step: Step) -> None:
        source = establish_step.dir / "clip.mp4"
        ffmpeg("-ss", str(video_seconds(source) - TWO_SHOT_BACKOFF), "-i", str(source), "-frames:v", "1", str(step.dir / "plate.png"))

    # the single reference for every segment, and the fixed reference the drift gate measures against
    two_shot = b.step("two_shot", {"backoff": TWO_SHOT_BACKOFF, "rule": "frame at video length - backoff, png"}, [establish_step], plate_two,
                      outputs=["plate.png"])

    segs: list[Step] = []
    for i, seg in enumerate(story["segments"], start=1):
        first = i == 1  # opens the scene instead of continuing; no Motion Context
        length = seg.get("length") or clip_length(seg["line"], first)
        prompt = segment_prompt(story, seg, length, first)
        prev = segs[-1] if segs else None
        seed = story["seed"] + 100 + i
        audio_dep = voices[seg["speaker"]]

        def render(step: Step, i=i, seg=seg, length=length, prompt=prompt, prev=prev, seed=seed, audio_dep=audio_dep) -> dict:
            from engine.transcribe import transcribe
            (step.dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            images = [to_input(two_shot.dir / "plate.png")]
            audio = to_input(audio_dep.dir / "voice.wav")
            prev_latent = f"{comfy_prefix(prev)}/clip_{i - 1:05d}.safetensors" if prev else None
            ref = load_reference(two_shot.dir / "plate.png")

            def attempt(n: int) -> dict:
                graph = clip_graph(prompt, length, seed + SEED_STRIDE * n, comfy_prefix(step, f"take{n}"), images=images, audio=audio,
                                   index=i, prev_latent=prev_latent, latent_prefix=comfy_prefix(step))
                take = saved_mp4(submit(graph, f"{step.name} take {n}"))
                words = transcribe(take)
                jumps = jump_frames(take)
                seconds = video_seconds(take)
                diffs = drift_diffs(sample_clip(take), ref)
                scores, bad = judge_take(seg["line"], words, jumps, diffs, seconds)
                print(f"{step.name} take {n}: {bad or 'accepted'}", flush=True)
                return {"seed": seed + SEED_STRIDE * n, "file": str(take), "jumps": jumps, **scores, "drift_max": round(max(diffs, default=0.0), 1),
                        "closing_silence": round(seconds - max((w["end"] for w in words), default=0.0), 3), "problems": bad, "words": words}

            try:
                takes, kept = run_takes(attempt, MAX_TRIES)
            except AcceptanceError as exc:
                (step.dir / "rejected.json").write_text(json.dumps(exc.takes, ensure_ascii=False, indent=1), encoding="utf-8")
                raise
            # the latent slot holds the last take, so the kept clip must be the last take too
            shutil.copy2(kept["file"], step.dir / "clip.mp4")
            (step.dir / "words.json").write_text(json.dumps(kept["words"], ensure_ascii=False), encoding="utf-8")
            frame_grid(step.dir / "clip.mp4", step.dir / "grid.jpg")
            return {"takes": [{k: v for k, v in t.items() if k != "words"} for t in takes]}

        estimate = 165 * length / 124 if first else 228 * length / 141
        deps = [two_shot, audio_dep] + ([prev] if prev else [])
        params = {"engine": ENGINE, "prompt": prompt, "length": length, "seed": seed, "index": i, "gates": gate_settings(),
                  "whisper": WHISPER, "reference": "two_shot plate", "backoff": TWO_SHOT_BACKOFF}
        step = b.step(f"seg{i}", params, deps, render,
                      outputs=["clip.mp4", "words.json", "grid.jpg", "prompt.txt", f"clip_{i:05d}.safetensors"],
                      recipe=["comfy.py", "prompts.py", "review.py", "transcribe.py", "script.py"], estimate=estimate, gpu=True)
        segs.append(step)

    def master(step: Step) -> dict:
        frames = [video_frames(s.dir / "clip.mp4") for s in segs]
        inputs, parts = [], []
        for n, (s, count) in enumerate(zip(segs, frames)):
            inputs += ["-i", str(s.dir / "clip.mp4")]
            parts.append(f"[{n}:v]setpts=PTS-STARTPTS,fps={FPS}[v{n}];"
                         f"[{n}:a]aresample={ENCODE['ar']},apad,atrim=end={count / FPS:.6f},asetpts=PTS-STARTPTS[a{n}]")
        graph = ";".join(parts) + ";" + "".join(f"[v{n}][a{n}]" for n in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
        ffmpeg(*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", ENCODE["vcodec"], "-crf", str(ENCODE["crf"]),
               "-pix_fmt", ENCODE["pix_fmt"], "-c:a", ENCODE["acodec"], "-b:a", ENCODE["ab"], "-ar", str(ENCODE["ar"]), str(step.dir / "master.mp4"))
        got = video_frames(step.dir / "master.mp4")
        if got != sum(frames):
            raise RuntimeError(f"master has {got} frames, the clips add up to {sum(frames)}")
        return {"frames": got, "clip_frames": frames}

    master_step = b.step("master", {"encode": ENCODE, "concat": CONCAT, "fps": FPS}, segs, master, outputs=["master.mp4"], estimate=12)

    def timing(step: Step) -> None:
        from engine.align import build_timing
        clips = [(video_seconds(s.dir / "clip.mp4"), json.loads((s.dir / "words.json").read_text(encoding="utf-8"))) for s in segs]
        data = build_timing(story, clips, video_seconds(master_step.dir / "master.mp4"))
        if abs(data["duration_check"]["delta"]) > 0.5 / FPS:
            raise RuntimeError(f"master length disagrees with the clips by {data['duration_check']['delta']}s")
        (step.dir / "timing.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    timing_step = b.step("timing", {"lines": [s["line"] for s in story["segments"]], "fps": FPS}, segs + [master_step], timing,
                         outputs=["timing.json"], recipe=["align.py", "script.py"])

    finish_params = {"overlays": story.get("overlays", []), "fade": story.get("fade_out", 0.0), "font": FONT,
                     "names": {s: [story["characters"][s].get("name"), story["characters"][s].get("role")] for s in SIDES}}

    def finish(step: Step) -> None:
        from engine.overlay import burn, compile_ass
        data = json.loads((timing_step.dir / "timing.json").read_text(encoding="utf-8"))
        ass = step.dir / "final.ass"
        ass.write_text(compile_ass(data, story, FONT), encoding="utf-8")
        burn(master_step.dir / "master.mp4", ass, step.dir / "final.mp4", data["duration"], story.get("fade_out", 0.0))
        if video_frames(step.dir / "final.mp4") != video_frames(master_step.dir / "master.mp4"):
            raise RuntimeError("final.mp4 and master.mp4 differ in frame count")

    final = b.step("final", finish_params, [master_step, timing_step], finish, outputs=["final.mp4", "final.ass"], recipe=["overlay.py"], estimate=15)

    def verify(step: Step) -> None:
        """The finished file's own audio, transcribed again from scratch. Not the per-segment transcripts the takes were judged on."""
        from engine.transcribe import transcribe
        spans = json.loads((timing_step.dir / "timing.json").read_text(encoding="utf-8"))["clips"]
        words = transcribe(final.dir / "final.mp4")
        rows, failed = [], []
        for n, (seg, span) in enumerate(zip(story["segments"], spans), start=1):
            inside = [w for w in words if span["start"] <= (w["start"] + w["end"]) / 2 < span["start"] + span["duration"]]
            scores, bad = dialogue_verdict(seg["line"], inside)
            rows.append({"seg": n, "line": spoken(seg["line"]), "heard": "".join(w["word"] for w in inside), **scores, "problems": bad})
            if bad:
                failed.append(f"segment {n}: {bad}")
        result = {"independent": True, "source": "audio of final.mp4, one pass, no script hint", "whisper": WHISPER, "gates": gate_settings(),
                  "segments": rows, "words": words, "passed": not failed}
        (step.dir / "verify.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        if failed:
            raise AcceptanceError("the finished video failed its independent dialogue check: " + "; ".join(failed))

    verify_step = b.step("verify", {"gates": gate_settings(), "whisper": WHISPER, "lines": [s["line"] for s in story["segments"]]},
                         [final, timing_step], verify, outputs=["verify.json"], recipe=["transcribe.py", "review.py", "script.py"], estimate=90)
    print(b.summary())
    if args.plan:
        return 0

    name = args.name or Path(args.story).stem
    partial = OUT / f".{name}.partial"
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    shutil.copy2(final.dir / "final.mp4", partial / "final.mp4")
    shutil.copy2(final.dir / "final.ass", partial / "final.ass")
    shutil.copy2(master_step.dir / "master.mp4", partial / "master.mp4")
    shutil.copy2(timing_step.dir / "timing.json", partial / "timing.json")
    shutil.copy2(verify_step.dir / "verify.json", partial / "verify.json")
    (partial / "story.json").write_text(json.dumps(story, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, s in enumerate(segs, start=1):
        shutil.copy2(s.dir / "clip.mp4", partial / f"seg{i}.mp4")
        shutil.copy2(s.dir / "grid.jpg", partial / f"seg{i}_grid.jpg")
        ffmpeg("-i", str(s.dir / "clip.mp4"), "-vn", "-ar", "16000", "-ac", "1", str(partial / f"seg{i}.16k.wav"))
    data = json.loads((timing_step.dir / "timing.json").read_text(encoding="utf-8"))
    report = {
        "steps": b.rows,
        "takes": {s.name: read_marker(s)["meta"].get("takes") for s in segs},
        "speech": [{"text": s["text"], "heard": s["heard"], "start": s["start"], "end": s["end"]} for s in data["segments"]],
        "anchors": data["anchors"],
        "anchor_source": data["anchor_source"],
        "segments_with_unheard_characters": data["segments_with_unheard_characters"],
        "duration_check": data["duration_check"],
        "render_seconds": {r["step"]: r["seconds"] for r in b.rows if r["gpu"] and r["state"] == "run"},
        "final_seconds": data["duration"],
        "lines": [spoken(s["line"]) for s in story["segments"]],
        "frames_per_second": FPS,
        "independent_check": "verify.json",
    }
    (partial / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out = OUT / name
    if out.exists():
        shutil.rmtree(out)
    partial.rename(out)
    print(f"FINAL {out / 'final.mp4'} ({data['duration']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
