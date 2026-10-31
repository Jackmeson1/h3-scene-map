"""The story file: the one input. Script text, word anchors, clip lengths, a schema check and a lint, all before any GPU time.

A line can carry anchors, `师傅，@{ask}今晚还开船吗？`. Overlays bind to the anchor, so they follow the
word when the line changes. The script is the only place spoken words live; prompts and captions read it.
"""

import json
import re
from pathlib import Path

from .script import ANCHOR, CAST_LENGTH, FPS, HEAD_FRAMES, LEAD_IN, SIDES, SPEECH_RATE, char_count, clip_length, spoken  # noqa: F401

RESERVED_ANCHORS = ("start", "end")
FORMATS_KNOWN = ("two_person_static",)
OVERLAY_TYPES = ("nameplate", "title")
MIN_LENGTH = 5
# Largest clip actually rendered so far is 158 frames. 209 (5 + 17 * 12) is a provisional engineering limit, NOT a
# verified model limit: nothing has been rendered above 158.
MAX_LENGTH = 209

# Whole phrases about a body leaving the frame or a head rotating. A bare verb is not enough: "chest rising and
# falling" and "a rising sense of dread" are fine. Each pattern needs a physical subject or a direction.
DRIFT_PHRASES = [
    re.compile(r"\b(turns?|turned|turning)\s+(her|his|their|its|the)?\s*(head|face|body|torso|shoulders?|back|whole body)\b", re.I),
    re.compile(r"\b(turns?|turned|turning)\s+(away|around|round|to face|toward|towards|back to)\b", re.I),
    re.compile(r"\brotat\w+\s+(her|his|their|its|the)?\s*(head|face|body|torso|shoulders?)\b", re.I),
    re.compile(r"\b(stands?|stood|standing)\s+up\b", re.I),
    re.compile(r"\b(rises?|rose|rising)\s+(from|out of|to\s+(her|his|their)\s+feet|to\s+stand|up\s+from)\b", re.I),
    re.compile(r"\bsit(s|ting)?\s+down\b", re.I),
    re.compile(r"\b(walks?|walking|steps?|stepping|leaves?|leaving|exits?|exiting)\s+(out\s+of|out|away|off|from)\s+(the\s+)?(frame|shot|picture|scene)\b", re.I),
    re.compile(r"\bleaves?\s+(the\s+)?(frame|shot)\b", re.I),
]
# Separate camera movements make the model cut. The word "camera" alone, repeated, is harmless.
CAMERA_MOVES = re.compile(r"\b(pans?|tilts?|zooms?|dolly|dollies|tracks?|pushes?\s+in|pulls?\s+back|cuts?\s+to|orbits?)\b", re.I)


def load(path: str, sets: list[str]) -> dict:
    story = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in sets:
        dotted, value = item.split("=", 1)
        parts = dotted.split(".")
        node = story
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        last = parts[-1]
        parsed = json.loads(value) if value[:1] in '[{"' or value.lstrip("-").replace(".", "").isdigit() else value
        if isinstance(node, list):
            node[int(last)] = parsed
        else:
            node[last] = parsed
    return story


def anchors(story: dict) -> set[str]:
    return {name for seg in story["segments"] for name in ANCHOR.findall(seg["line"])} | set(RESERVED_ANCHORS)


def _nonempty(node, key) -> bool:
    return isinstance(node, dict) and isinstance(node.get(key), str) and node[key].strip() != ""


def validate_schema(story) -> list[str]:
    """Required fields and types. Anything that would otherwise be a KeyError or a silently ignored field after GPU time."""
    if not isinstance(story, dict):
        return ["story must be a JSON object"]
    errors = []
    for key in ("scene", "style", "soundscape"):
        if not _nonempty(story, key):
            errors.append(f"'{key}' is required and must be a non-empty string")
    if not isinstance(story.get("seed"), int) or isinstance(story.get("seed"), bool):
        errors.append("'seed' is required and must be an integer")
    if story.get("format", FORMATS_KNOWN[0]) not in FORMATS_KNOWN:
        errors.append(f"format '{story.get('format')}' is unknown, known: {list(FORMATS_KNOWN)}")
    fade = story.get("fade_out", 0.0)
    if not isinstance(fade, (int, float)) or isinstance(fade, bool) or fade < 0:
        errors.append("'fade_out' must be a number of seconds >= 0")
    chars = story.get("characters")
    if not isinstance(chars, dict):
        errors.append("'characters' is required and must be an object with left and right")
        chars = {}
    for side in SIDES:
        who = chars.get(side)
        if who is None:
            errors.append(f"characters.{side} is missing")
            continue
        for key in ("desc", "voice", "they", "their", "cast_line"):
            if not _nonempty(who, key):
                errors.append(f"characters.{side}.{key} is required and must be a non-empty string")
    segs = story.get("segments")
    if not isinstance(segs, list) or not segs:
        errors.append("'segments' is required and must be a non-empty list")
        segs = []
    for i, seg in enumerate(segs, start=1):
        if not isinstance(seg, dict):
            errors.append(f"segment {i} must be an object")
            continue
        needed = ["speaker", "line"] + ([] if "prompt" in seg else ["intent", "before", "after", "delivery"])
        for key in needed:
            if not _nonempty(seg, key):
                errors.append(f"segment {i}: '{key}' is required and must be a non-empty string")
        if "length" in seg and (not isinstance(seg["length"], int) or isinstance(seg["length"], bool)):
            errors.append(f"segment {i}: 'length' must be an integer number of frames")
    overlays = story.get("overlays", [])
    if not isinstance(overlays, list):
        errors.append("'overlays' must be a list")
        overlays = []
    for n, item in enumerate(overlays):
        where = f"overlays.{n}"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        kind = item.get("type")
        if kind not in OVERLAY_TYPES:
            errors.append(f"{where}: type '{kind}' is unknown, known: {list(OVERLAY_TYPES)}")
            continue
        if not _nonempty(item, "at"):
            errors.append(f"{where}: 'at' (an anchor name) is required")
        if "lasts" in item and (not isinstance(item["lasts"], (int, float)) or isinstance(item["lasts"], bool) or item["lasts"] <= 0):
            errors.append(f"{where}: 'lasts' must be a positive number of seconds")
        if "offset" in item and (not isinstance(item["offset"], (int, float)) or isinstance(item["offset"], bool)):
            errors.append(f"{where}: 'offset' must be a number of seconds")
        if kind == "title" and not _nonempty(item, "text"):
            errors.append(f"{where}: a title needs non-empty 'text'")
        if kind == "nameplate":
            who = item.get("who")
            if who not in SIDES:
                errors.append(f"{where}: a nameplate needs who = left or right")
            elif not _nonempty(chars.get(who), "name"):
                errors.append(f"{where}: characters.{who}.name is required for a nameplate")
    return errors


def lint(story: dict) -> list[str]:
    """Everything here would otherwise be discovered after paying for a render."""
    errors = validate_schema(story)
    if errors:
        return errors  # the checks below assume the shape is right
    from .prompts import planned_seconds
    seen = []
    for side in SIDES:
        cast = story["characters"][side]["cast_line"]
        room = CAST_LENGTH / FPS - 0.5 - 0.1  # the prompt starts the line at 0.5 s; it must end inside the clip. The casting clip is not gated and needs no closing hold
        if planned_seconds(cast) > room:
            errors.append(f"characters.{side}.cast_line takes {planned_seconds(cast):.1f}s to say, the casting clip only has {room:.1f}s")
    for i, seg in enumerate(story["segments"], start=1):
        where = f"segment {i}"
        seen += ANCHOR.findall(seg["line"])
        if seg["speaker"] not in SIDES:
            errors.append(f"{where}: speaker must be left or right")
        if char_count(seg["line"]) == 0:
            errors.append(f"{where}: empty line")
        for name in ANCHOR.findall(seg["line"]):
            if name in RESERVED_ANCHORS:
                errors.append(f"{where}: anchor '{name}' is reserved")
        for field in ("intent", "before", "after", "prompt"):
            text = seg.get(field, "")
            for pattern in DRIFT_PHRASES:
                hit = pattern.search(text)
                if hit:
                    errors.append(f"{where}.{field}: '{hit.group(0)}' drifts heads off axis or a body out of frame; describe a held pose instead")
                    break
        length = seg.get("length")
        if length is not None:
            if length % 17 != 5:
                errors.append(f"{where}: length {length} is not 5 + 17k frames")
            if length < MIN_LENGTH or length > MAX_LENGTH:
                errors.append(f"{where}: length {length} is outside {MIN_LENGTH}..{MAX_LENGTH} frames")
            if length < clip_length(seg["line"], i == 1):
                errors.append(f"{where}: length {length} is too short for the line, needs {clip_length(seg['line'], i == 1)}")
        if clip_length(seg["line"], i == 1) > MAX_LENGTH:
            errors.append(f"{where}: the line needs {clip_length(seg['line'], i == 1)} frames, above the {MAX_LENGTH} limit; split it")
        if "prompt" in seg:
            tag = f"<d>[Mandarin]{spoken(seg['line'])}</d>"
            if seg["prompt"].count(tag) != 1:
                errors.append(f"{where}: prompt must contain the script line exactly once as {tag}")
            if "no subtitles" not in seg["prompt"].lower():
                errors.append(f"{where}: prompt must end with 'no subtitles'")
            moves = {m.group(0).lower() for m in CAMERA_MOVES.finditer(seg["prompt"])}
            if moves:
                errors.append(f"{where}: camera movement in the prompt ({sorted(moves)}) makes the model cut")
    dupes = {name for name in seen if seen.count(name) > 1}
    if dupes:
        errors.append(f"anchors used twice: {sorted(dupes)}")
    known = anchors(story)
    for n, item in enumerate(story.get("overlays", [])):
        if item["at"] not in known:
            errors.append(f"overlays.{n} ({item['type']}) binds to unknown anchor '{item['at']}'")
    return errors
