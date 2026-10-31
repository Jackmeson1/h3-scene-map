"""From what the model actually said to a time on every script character.

Prompts only ask for timing, so captions and overlays read the performance instead: Whisper hears the
clip with no script hint, then the script is mapped onto what was heard. Anything misheard, such as a
homophone, takes its time from the characters around it. Times are clamped to the clip, kept monotonic, and
every character that was not heard directly is flagged in timing.json.
"""

from difflib import SequenceMatcher

from .script import ANCHOR, spoken
from .transcribe import heard_chars

def match_score(line: str, words: list[dict]) -> float:
    want = "".join(c for c in spoken(line) if c.isalnum())
    got = "".join(c for c, _, _ in heard_chars(words))
    return SequenceMatcher(None, want, got, autojunk=False).ratio()


def script_times(line: str, words: list[dict], fallback: tuple, dur: float = None):
    """([char, start, end] for every character of the spoken line punctuation included, info).

    info = {"fallback": bool, "extrapolated": int, "source": [ "heard" | "extrapolated" | "fallback" per spoken character ]}.
    With dur given, every time is clamped into [0, dur] and the sequence is non-decreasing.
    """
    text = spoken(line)
    slots = [i for i, c in enumerate(text) if c.isalnum()]
    want = "".join(text[i] for i in slots)
    heard = heard_chars(words)
    got = "".join(c for c, _, _ in heard)
    times = [None] * len(want)
    source = ["extrapolated"] * len(want)
    for block in SequenceMatcher(None, want, got, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            times[block.a + k] = heard[block.b + k][1:]
            source[block.a + k] = "heard"
    known = [i for i, t in enumerate(times) if t]
    used_fallback = False
    if not known:
        used_fallback = True
        step = (fallback[1] - fallback[0]) / max(len(want), 1)
        times = [(fallback[0] + i * step, fallback[0] + (i + 1) * step) for i in range(len(want))]
        source = ["fallback"] * len(want)
    else:
        for i, t in enumerate(times):
            if t:
                continue
            before = max((k for k in known if k < i), default=None)
            after = min((k for k in known if k > i), default=None)
            if before is None:
                span = times[after][1] - times[after][0]
                times[i] = (times[after][0] - span * (after - i), times[after][0] - span * (after - i - 1))
            elif after is None:
                span = times[before][1] - times[before][0]
                times[i] = (times[before][1] + span * (i - before - 1), times[before][1] + span * (i - before))
            else:
                step = (times[after][0] - times[before][1]) / (after - before)
                times[i] = (times[before][1] + step * (i - before - 1), times[before][1] + step * (i - before))
    times = clamp_times(times, dur)
    out, cursor = [], 0
    for i, c in enumerate(text):
        if cursor < len(times) and i == slots[cursor]:
            out.append([c, round(times[cursor][0], 3), round(times[cursor][1], 3)])
            cursor += 1
        else:
            at = out[-1][2] if out else (round(times[0][0], 3) if times else 0.0)
            out.append([c, at, at])
    info = {"fallback": used_fallback, "extrapolated": sum(1 for s in source if s != "heard"), "source": source}
    return out, info


def clamp_times(times: list, dur: float = None) -> list:
    """Inside [0, dur], start <= end, and never going backwards from one character to the next."""
    out, floor = [], 0.0
    for s, e in times:
        s = max(s, floor, 0.0)
        e = max(e, s)
        if dur is not None:
            s, e = min(s, dur), min(e, dur)
        out.append((s, e))
        floor = s
    return out


def anchor_times(line: str, chars: list[list], source: list = None) -> tuple[dict, dict]:
    """An anchor lands on the first spoken character after it. Returns (times, how each was obtained)."""
    found, how, removed = {}, {}, 0
    for m in ANCHOR.finditer(line):
        pos = m.start() - removed
        removed += len(m.group(0))
        following = [(k, c) for k, c in enumerate(chars[pos:], start=pos) if c[0].isalnum()]
        found[m.group(1)] = following[0][1][1] if following else chars[-1][2]
        if following and source is not None:
            alnum_index = sum(1 for c in chars[:following[0][0]] if c[0].isalnum())
            how[m.group(1)] = source[alnum_index] if alnum_index < len(source) else "extrapolated"
        else:
            how[m.group(1)] = "extrapolated" if source is not None else "unknown"
    return found, how


def build_timing(story: dict, clips: list[tuple], master_duration: float = None) -> dict:
    """clips: (clip seconds, words) per segment, the seconds taken from the clip's video frames.
    Times in the result are on the finished video's clock. With master_duration, the total is the real master's."""
    segments, marks, how_marks, offset, spans = [], {"start": 0.0}, {"start": "exact"}, 0.0, []
    for seg, (dur, words) in zip(story["segments"], clips):
        chars, info = script_times(seg["line"], words, (0.3, max(dur - 0.3, 0.3)), dur)
        shifted = [[c, round(s + offset, 3), round(e + offset, 3)] for c, s, e in chars]
        times, how = anchor_times(seg["line"], shifted, info["source"])
        marks.update(times)
        how_marks.update(how)
        segments.append({"speaker": seg["speaker"], "text": spoken(seg["line"]), "chars": shifted,
                         "start": shifted[0][1], "end": shifted[-1][2],
                         "heard": "".join(w["word"] for w in words), "match": round(match_score(seg["line"], words), 3),
                         "fallback": info["fallback"], "extrapolated_chars": info["extrapolated"],
                         "speech_end_in_clip": round(max((w["end"] for w in words), default=0.0), 3),
                         "closing_silence": round(dur - max((w["end"] for w in words), default=0.0), 3)})
        spans.append({"start": round(offset, 3), "duration": round(dur, 3)})
        offset += dur
    total = round(offset, 3)
    check = {"clip_sum": total, "master": None if master_duration is None else round(master_duration, 3)}
    if master_duration is not None:
        check["delta"] = round(master_duration - offset, 3)
        total = round(master_duration, 3)
    marks["end"] = total
    how_marks["end"] = "exact"
    flagged = [i + 1 for i, s in enumerate(segments) if s["fallback"] or s["extrapolated_chars"]]
    return {"duration": total, "duration_check": check, "clips": spans, "segments": segments, "anchors": marks,
            "anchor_source": how_marks, "segments_with_unheard_characters": flagged}
