#!/usr/bin/env python3
"""Turns the pulled clips into something a person can rate: a 2 fps contact sheet and a one-line summary per clip, and scene_results/index.md,
grouped by scene, with the author's claims as a checklist. Nothing here accepts or rejects a clip.

Usage: rate_pack.py [project root]       (default: the folder above scripts/)
"""
import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path


def grid(clip: Path, out: Path, cols: int = 6) -> bool:
    n = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(clip)],
                       capture_output=True, text=True).stdout.strip().rstrip(",")
    if not n.isdigit():
        return False
    rows = max(1, -(-int(int(n) / 24 * 2 + 1) // cols))
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-vf", f"fps=2,scale=320:-1,tile={cols}x{rows}", "-frames:v", "1", "-q:v", "4", str(out)])
    return r.returncode == 0 and out.exists()


def script_line(prompt: str):
    m = re.search(r"<d>\[Mandarin\](.*?)</d>", prompt)
    return m.group(1) if m else None


def plain(text: str) -> str:
    return re.sub(r"[^\w]", "", text or "")


def clip_summary(scene_id: str, seed, clip: dict, defs_clip: dict, seconds) -> str:
    bits = [f"{scene_id} seed {seed} {clip['name']} ({clip.get('frames', '?')} f)", f"intent: {defs_clip.get('intent') or clip.get('intent') or ''}"]
    if clip.get("mean_db") is not None:
        bits.append(f"mean {clip['mean_db']} dB, peak {clip['max_db']} dB")
    fs = clip.get("frame_stats", {})
    if fs:
        bits.append(f"adjacent-frame max {fs['adjacent_max']} (cuts over 15: {fs['adjacent_over_15']}), drift from first frame max {max(fs['drift_from_first_frame_2hz'])}")
    line = script_line(defs_clip.get("prompt", ""))
    if line is not None and "transcript_blind" in clip:
        bits.append(f"script '{line}' / blind transcript '{clip['transcript_blind']}' (similarity {SequenceMatcher(None, plain(line), plain(clip['transcript_blind'])).ratio():.2f}, a measurement only)")
    if seconds is not None:
        bits.append(f"job render {seconds}s")
    return "; ".join(bits)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    results = root / "scene_results"
    defs = json.loads((root / "scenes" / "scenes.json").read_text(encoding="utf-8"))
    entries = [(s["id"], s["title"], s["whitepaper"], s["claims"], {c["name"]: c for c in s["clips"]}, s["seeds"]) for s in defs["scenes"]]
    v9 = defs["v9"]
    entries.append(("v9", v9["title"], v9["whitepaper"], v9["claims"], {}, v9["seeds"]))
    lines = ["# Scene results, for rating", "",
             "Gates were off: nothing below was rejected or retaken. Every number is a measurement. Rate each claim as held / partly / failed, and write why.", ""]
    missing = []
    for sid, title, section, claims, defs_clips, seeds in entries:
        lines += [f"## {sid}: {title}", f"Whitepaper / article: {section}", "", "Claims to rate:"] + [f"- [ ] {c}" for c in claims] + [""]
        for seed in seeds:
            job = results / f"{sid}__{seed}"
            meta_path = job / "meta.json"
            if not meta_path.exists():
                failed = job / "FAILED.json"
                lines.append(f"### seed {seed}: " + ("FAILED in the box, see queue" if failed.exists() else "not rendered"))
                missing.append(f"{sid}__{seed}")
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            lines.append(f"### seed {seed}: render {meta['render_seconds']}s, peak VRAM {meta.get('peak_vram_mb')} MB, wall {meta.get('wall_seconds')}s")
            dbs = []
            for clip in meta["clips"]:
                mp4 = job / clip["file"]
                sheet = job / f"{Path(clip['file']).stem}_grid.jpg"
                has_grid = grid(mp4, sheet)
                summary = clip_summary(sid, seed, clip, defs_clips.get(clip["name"], {}), None)
                (job / f"{Path(clip['file']).stem}.summary.txt").write_text(summary + "\n", encoding="utf-8")
                rel = lambda p: p.relative_to(results).as_posix()
                lines += [f"- video: `{rel(mp4)}`", f"  - sheet: `{rel(sheet)}`" if has_grid else "  - sheet: could not be made", f"  - {summary}"]
                dbs.append(clip.get("mean_db"))
            if sid == "v9" and len(dbs) == 4 and None not in dbs:
                lines.append(f"  - volume steps (the author reports +8.2 dB for seg1 to seg3 and +7.6 dB for seg2 to seg4): seg3 - seg1 = {dbs[2] - dbs[0]:+.1f} dB, seg4 - seg2 = {dbs[3] - dbs[1]:+.1f} dB")
            if meta.get("not_carried_over"):
                lines += ["  - not carried over from the author's graph:"] + [f"    - {x}" for x in meta["not_carried_over"]]
            lines.append("")
    voice = results / "v9_voiceseed" / "meta.json"
    lines += ["## voice seeds (V9 first pass, no reference audio)", ""]
    lines.append(json.dumps(json.loads(voice.read_text(encoding="utf-8"))["assets"], ensure_ascii=False, indent=1) if voice.exists() else "not rendered")
    if missing:
        lines += ["", f"Missing or failed: {', '.join(missing)}"]
    (results / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {results / 'index.md'}; {len(missing)} missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
