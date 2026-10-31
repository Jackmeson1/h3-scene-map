#!/usr/bin/env python3
"""Draw the README figures as SVG, one light and one dark version of each.

Usage: make_figures.py <figures folder>
"""

import os
import sys

FONT = "system-ui,-apple-system,'Segoe UI',sans-serif"
LIGHT = {"bg": "#fcfcfb", "ink": "#0b0b0b", "soft": "#52514e", "muted": "#898781", "line": "#e1e0d9", "edge": "#c3c2b7", "bar": "#2a78d6", "box": "#f0efec"}
DARK = {"bg": "#1a1a19", "ink": "#f0efec", "soft": "#c3c2b7", "muted": "#898781", "line": "#2c2c2a", "edge": "#383835", "bar": "#3987e5", "box": "#2c2c2a"}
STATUS = {"u": ("#0ca30c", "#ffffff"), "x": ("#fab219", "#0b0b0b"), "f": ("#d03b3b", "#ffffff")}

# scene, usable, fixable, failed, render minutes per take
SCENES = [
    ("Monologue close-up", 3, 0, 0, 2.5),
    ("Reaction close-up", 3, 0, 0, 1.3),
    ("Over-the-shoulder pair", 3, 0, 0, 5.4),
    ("Walk and talk", 3, 0, 0, 4.1),
    ("Two-person dialogue", 2, 0, 1, 2.7),
    ("Emotional outburst", 2, 1, 0, 2.75),
    ("Pouring tea", 2, 1, 0, 4.0),
    ("Fight, 15 s", 1, 1, 1, 9.5),
    ("Stand up, camera follows", 0, 3, 0, 2.75),
    ("Solo dance, 12 s", 0, 1, 2, 8.4),
    ("Four-segment scene, 20 s", 0, 1, 2, 12.8),
]


def text(x, y, s, fill, size=14, anchor="start", weight=400) -> str:
    return f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>'


def icon(kind, x, y, colour) -> str:
    paths = {"u": f"M{x + 8} {y + 15}l5 5 9-11", "x": f"M{x + 8} {y + 15}h14", "f": f"M{x + 9} {y + 9}l12 12M{x + 21} {y + 9}l-12 12"}
    return f'<path d="{paths[kind]}" fill="none" stroke="{colour}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'


def square(kind, x, y) -> str:
    fill, mark = STATUS[kind]
    return f'<rect x="{x}" y="{y}" width="30" height="30" rx="4" fill="{fill}"/>' + icon(kind, x, y, mark)


def results(t) -> str:
    left, cells, bars, top, row = 216, 216 + 3 * 36, 400, 76, 40
    width, height = 720, top + row * len(SCENES) + 12
    scale = 250 / 12.8
    p = [f'<rect width="{width}" height="{height}" fill="{t["bg"]}"/>']
    x = 16
    for kind, name, count in (("u", "Usable", 19), ("x", "Fixable", 8), ("f", "Failed", 6)):
        p += [square(kind, x, 10), text(x + 38, 31, f"{name}: {count}", t["ink"], 14, weight=600)]
        x += 130
    p += [text(left, 64, "Three takes", t["soft"], 12), text(bars, 64, "Render minutes per take", t["soft"], 12)]
    for i, (name, u, x_, f, minutes) in enumerate(SCENES):
        y = top + i * row
        if i:
            p.append(f'<line x1="16" x2="{width - 16}" y1="{y - 5}" y2="{y - 5}" stroke="{t["line"]}"/>')
        p.append(text(16, y + 20, name, t["ink"], 14))
        for j, kind in enumerate("u" * u + "x" * x_ + "f" * f):
            p.append(square(kind, left + j * 36, y))
        w = minutes * scale
        p.append(f'<rect x="{bars}" y="{y + 9}" width="{w:.1f}" height="12" rx="4" fill="{t["bar"]}"/>')
        p.append(text(bars + w + 8, y + 20, f"{minutes:g}", t["soft"], 12))
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="{FONT}">'
    return head + "".join(p) + "</svg>"


def box(x, y, w, h, title, lines, t) -> str:
    p = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{t["box"]}" stroke="{t["edge"]}"/>', text(x + 12, y + 24, title, t["ink"], 14, weight=600)]
    p += [text(x + 12, y + 44 + i * 17, line, t["soft"], 12) for i, line in enumerate(lines)]
    return "".join(p)


def arrow(x1, y1, x2, y2, t) -> str:
    return f'<path d="M{x1} {y1}L{x2} {y2}" stroke="{t["soft"]}" stroke-width="1.5" fill="none" marker-end="url(#a)"/>'


def pipeline(t) -> str:
    width, height, w, h, y, gap = 720, 196, 156, 104, 14, 24
    xs = [16 + i * (w + gap) for i in range(4)]
    p = [f'<rect width="{width}" height="{height}" fill="{t["bg"]}"/>',
         f'<defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M1 1l6 3-6 3" fill="none" stroke="{t["soft"]}" stroke-width="1.5"/></marker></defs>',
         box(xs[0], y, w, h, "Inputs", ["Character portraits", "Voice sample", "Line and timing"], t),
         box(xs[1], y, w, h, "Prompt", ["Six fixed sections:", "who, plot, what stays,", "action, sound, music"], t),
         box(xs[2], y, w, h, "H3 render", ["12 steps on one GPU", "Picture and speech", "come out together"], t),
         box(xs[3], y, w, h, "Clip", ["24 fps, 1344x768", "A few seconds long", "with its own audio"], t)]
    p += [arrow(xs[i] + w + 2, y + h / 2, xs[i + 1] - 3, y + h / 2, t) for i in range(3)]
    mid, low = xs[3] + w / 2, y + h
    start = xs[2] + w / 2
    p.append(f'<path d="M{mid} {low + 2}V{low + 44}H{start}V{low + 4}" stroke="{t["soft"]}" stroke-width="1.5" fill="none" marker-end="url(#a)"/>')
    p.append(text((mid + start) / 2, low + 62, "Longer scenes: the last 22 frames of each clip start the next one", t["soft"], 12, "middle"))
    head = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="{FONT}">'
    return head + "".join(p) + "</svg>"


def main() -> None:
    root = sys.argv[1]
    for name, draw in (("scene-results", results), ("pipeline", pipeline)):
        for suffix, theme in (("", LIGHT), ("-dark", DARK)):
            with open(os.path.join(root, f"{name}{suffix}.svg"), "w", encoding="utf-8", newline="\n") as f:
                f.write(draw(theme))


if __name__ == "__main__":
    main()
