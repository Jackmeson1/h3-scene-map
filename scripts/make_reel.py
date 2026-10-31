#!/usr/bin/env python3
"""Cut the highlight reel from the scene test renders: the best take of each scene, labelled with its rating.

Usage: make_reel.py <folder of scene renders> <output.mp4>
The reel is sized to stay under GitHub's 10 MB limit for video in a README.
"""

import json
import os
import subprocess
import sys
import tempfile

FONT = "C\\:/Windows/Fonts/arial.ttf"
W, H = 960, 548
TARGET_MB = 9.4
AUDIO_KBPS = 96
CONTEXT = 22 / 24  # the frames a continuing clip repeats from the one before it

# (job folder, clip, start second, end second or None, label)
PICKS = [
    ("s01_monologue_cu__2026110012", "clip1.mp4", 0, None, "Monologue close-up: usable"),
    ("s02_dialogue_two_shot__2026110021", "clip1.mp4", 0, None, "Two-person dialogue: usable"),
    ("s03_ots_reverse_pair__2026110032", "clipA_S2_over_S1.mp4", 0, None, "Over-the-shoulder pair: usable"),
    ("s03_ots_reverse_pair__2026110032", "clipB_S1_over_S2.mp4", 0, None, "Over-the-shoulder pair: usable"),
    ("s04_walk_and_talk__2026110042", "clip1.mp4", 0, None, "Walk and talk: usable"),
    ("s05_outburst_push_in__2026110051", "clip1.mp4", 0, None, "Emotional outburst: usable"),
    ("s07_reaction_cu__2026110072", "clip1.mp4", 0, None, "Reaction close-up: usable"),
    ("s10_hands_tea__2026110102", "clip1.mp4", 0, None, "Pouring tea: usable"),
    ("s08_two_fighters__2026110083", "segA.mp4", 1.5, None, "Fight, first half: usable once trimmed"),
    ("s08_two_fighters__2026110083", "segB.mp4", CONTEXT, None, "Fight, second half: usable"),
    ("s06_stand_up_compensation__2026110063", "clip1.mp4", 0, None, "Stand up: fixable, the head reaches the top edge first"),
    ("s09_solo_dance__2026110093", "clip1.mp4", 0, None, "Solo dance: fixable, the leap is cropped"),
    ("v9__2026102201", "seg4.mp4", 0, None, "Four-segment scene: failed, split screen"),
]


def run(*args: str, cwd: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True, cwd=cwd)


def seconds(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                         check=True, capture_output=True, text=True).stdout
    return float(json.loads(out)["format"]["duration"])


def main() -> None:
    root, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    with tempfile.TemporaryDirectory() as tmp:
        names = []
        with open(os.path.join(tmp, "note.txt"), "w", encoding="utf-8") as f:
            f.write("Machine-generated with MiniMax-H3")
        for i, (job, clip, start, end, label) in enumerate(PICKS):
            with open(os.path.join(tmp, f"l{i}.txt"), "w", encoding="utf-8") as f:
                f.write(label)
            text = (f"scale={W}:{H},fps=24,format=yuv420p,"
                    f"drawtext=fontfile='{FONT}':textfile=l{i}.txt:x=20:y=20:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=8,"
                    f"drawtext=fontfile='{FONT}':textfile=note.txt:x=w-tw-14:y=h-th-12:fontsize=15:fontcolor=white@0.75")
            cut = ["-ss", str(start)] + (["-to", str(end)] if end else [])
            name = f"p{i:02d}.mp4"
            run(*cut, "-i", os.path.join(root, job, clip), "-vf", text, "-af", "aresample=48000,aformat=channel_layouts=stereo",
                "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k", name, cwd=tmp)
            names.append(name)
        with open(os.path.join(tmp, "list.txt"), "w", encoding="utf-8") as f:
            f.writelines(f"file '{n}'\n" for n in names)
        run("-f", "concat", "-i", "list.txt", "-c", "copy", "all.mp4", cwd=tmp)
        video_kbps = int(TARGET_MB * 8000 / seconds(os.path.join(tmp, "all.mp4"))) - AUDIO_KBPS
        for number, tail in ((1, ["-an", "-f", "null", "NUL"]), (2, ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-movflags", "+faststart", out])):
            run("-i", "all.mp4", "-fps_mode", "cfr", "-r", "24", "-c:v", "libx264", "-preset", "slow", "-b:v", f"{video_kbps}k", "-pass", str(number), *tail, cwd=tmp)


if __name__ == "__main__":
    main()
