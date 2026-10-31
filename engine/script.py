"""The parts of the story format the render path depends on: timing constants, anchors, clip length.

Kept apart from story.py (schema, lint, loading) so that editing a lint rule does not change the recipe of any render step.
"""

import re

FPS = 24
HEAD_FRAMES = 22  # frames of the previous clip a continuing clip is conditioned on; they are trimmed from its output

# How long a line takes to say, fitted on real Whisper word spans:
# 11 distinct lines from earlier test renders, three voices, two scenes.
#   seconds = chars / 4.55 + 0.72 * pauses     (pauses = punctuation inside the line)
# Residual rms 0.37 s, largest underestimate 0.70 s, largest overestimate 0.66 s. The older flat 3.6 chars/s with no pauses
# had rms 0.55 s. The pause term matters because a comma costs the model about 0.7 s of silence.
SPEECH_RATE = 4.55
PAUSE_COST = 0.72
SPAN_MARGIN = 0.75  # added to the fit for sizing a clip: the largest underestimate in the data (0.70 with the unrounded fit, 0.73 with the rounded numbers above), plus a little
# Seconds from the start of the visible clip to the first heard word: 0.00 to 1.46 over 10 clips (mean 0.78). The prompt asks for 0.45.
ONSET_MAX = 1.5
LEAD_IN = 0.45  # where the prompt places the first word
MIN_CLOSING_SILENCE = 0.5  # the gate in review.py: speech must end at least this long before the clip end
ANCHOR = re.compile(r"@\{([\w-]+)\}")

SIDES = ("left", "right")
CAST_LENGTH = 124  # frames of the standalone casting clip


def spoken(line: str) -> str:
    return ANCHOR.sub("", line)


PAUSE_MARKS = re.compile(r"[，、；：,;:！？!?。](?=.)")


def char_count(line: str) -> int:
    return sum(c.isalnum() for c in spoken(line))


def pause_count(line: str) -> int:
    """Punctuation inside the line, followed by more text. The final stop does not cost a pause."""
    return len(PAUSE_MARKS.findall(spoken(line)))


def speech_seconds(line: str) -> float:
    """What the prompt's timecodes are built on: the fitted time to say the line."""
    return max(1.6, char_count(line) / SPEECH_RATE + pause_count(line) * PAUSE_COST)


def speech_seconds_safe(line: str) -> float:
    """What clip length is sized on: the fit plus its largest underestimate."""
    return speech_seconds(line) + SPAN_MARGIN


def clip_length(line: str, first: bool) -> int:
    """Smallest legal frame count (5 + 17k) in which the line, started as late as the model has been seen to start it and run as
    long as the fit's worst case, still ends MIN_CLOSING_SILENCE before the clip does. A continuing clip also carries HEAD_FRAMES
    that are trimmed from its output, so they are added on top."""
    head = 0.0 if first else HEAD_FRAMES / FPS
    need = head + ONSET_MAX + speech_seconds_safe(line) + MIN_CLOSING_SILENCE
    frames = 124 if first else 141
    while frames / FPS < need:
        frames += 17
    return frames
