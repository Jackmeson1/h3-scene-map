#!/usr/bin/env python3
"""The code-rendered layer: karaoke captions, nameplates and titles compiled to ASS, burned by ffmpeg.

No model and no GPU are involved, so this step can rerun anywhere, including on a laptop after the
G4 is gone. Everything binds to word anchors from timing.json, never to a typed-in second.

Standalone: overlay.py <master.mp4> <timing.json> <story.json> <out.mp4> [font]
"""

import json
import subprocess
import sys
from pathlib import Path

W, H = 1344, 768
DEFAULT_LASTS = {"nameplate": 2.6, "title": 2.0}  # one place, so the position and the display time agree
SPEAKER_COLOR = {"left": "&H9FD8FF&", "right": "&HFFE0B0&"}


def ass_time(sec: float) -> str:
    cs = max(0, int(round(sec * 100)))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"


def header(font: str) -> str:
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
           "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
    styles = [
        f"Style: Sub,{font},36,&H00FFFFFF,&H28FFFFFF,&H90000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,2,60,60,34,1",
        f"Style: Plate,{font},32,&H00FFFFFF,&H00FFFFFF,&H70181818,&H70181818,1,0,0,0,100,100,2,0,3,10,0,1,0,0,0,1",
        f"Style: Title,{font},76,&H00FFFFFF,&H00FFFFFF,&H80000000,&H00000000,1,0,0,0,100,100,14,0,1,2,0,5,0,0,0,1",
    ]
    return ("[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            f"[V4+ Styles]\n{fmt}\n" + "\n".join(styles) +
            "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def caption(seg: dict) -> str:
    """One karaoke line: each character fills in the speaker's color as it is spoken."""
    chars = seg["chars"]
    text = ""
    for i, (c, start, _) in enumerate(chars):
        following = chars[i + 1][1] if i + 1 < len(chars) else seg["end"]
        text += "{\\kf%d}%s" % (max(0, round((following - start) * 100)), c)
    return (f"Dialogue: 1,{ass_time(seg['start'])},{ass_time(seg['end'] + 0.45)},Sub,,0,0,0,,"
            f"{{\\1c{SPEAKER_COLOR[seg['speaker']]}\\fad(80,160)}}{text}\n")


def lasts_of(item: dict) -> float:
    return item.get("lasts", DEFAULT_LASTS[item["type"]])


def nameplate(item: dict, who: dict, at: float) -> str:
    left = item["who"] == "left"
    x, y, drift = (70, 150, 22) if left else (W - 70, 150, -22)
    align = 7 if left else 9
    body = f"{who['name']}\\N{{\\fs21\\b0\\fsp1}}{who.get('role', '')}"
    return (f"Dialogue: 2,{ass_time(at)},{ass_time(at + lasts_of(item))},Plate,,0,0,0,,"
            f"{{\\an{align}\\move({x - drift},{y},{x},{y},0,380)\\fad(380,320)}}{body}\n")


def title(item: dict, at: float) -> str:
    return (f"Dialogue: 3,{ass_time(at)},{ass_time(at + lasts_of(item))},Title,,0,0,0,,"
            f"{{\\an5\\pos({W // 2},{H // 2})\\fad(500,500)}}{item['text']}\n")


def compile_ass(timing: dict, story: dict, font: str) -> str:
    out = header(font)
    out += "".join(caption(seg) for seg in timing["segments"])
    for item in story.get("overlays", []):
        lasts = lasts_of(item)
        at = timing["duration"] - lasts if item["at"] == "end" else timing["anchors"][item["at"]]
        at += item.get("offset", 0.0)
        if item["type"] == "nameplate":
            out += nameplate(item, story["characters"][item["who"]], at)
        elif item["type"] == "title":
            out += title(item, at)
    return out


def burn(master: Path, ass: Path, out: Path, duration: float, fade: float = 0.0) -> None:
    vf = f"ass={ass.name}" + (f",fade=t=out:st={duration - fade:.2f}:d={fade}" if fade else "")
    af = ["-af", f"afade=t=out:st={duration - fade:.2f}:d={fade}"] if fade else []
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(master.resolve()), "-vf", vf, "-c:v", "libx264", "-crf", "16",
                    "-pix_fmt", "yuv420p", *af, "-c:a", "aac", "-b:a", "192k", "-ar", "32000", str(out.resolve())],
                   check=True, cwd=ass.parent)


def main() -> None:
    master, timing_path, story_path, out = [Path(p) for p in sys.argv[1:5]]
    font = sys.argv[5] if len(sys.argv) > 5 else "Microsoft YaHei"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    story = json.loads(story_path.read_text(encoding="utf-8"))
    ass = out.with_suffix(".ass")
    ass.write_text(compile_ass(timing, story, font), encoding="utf-8")
    burn(master, ass, out, timing["duration"], story.get("fade_out", 0.0))


if __name__ == "__main__":
    main()
