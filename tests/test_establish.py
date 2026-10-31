"""Establishing shot, face check, speech model and the lengths it gives, the prompts."""
import numpy as np
import pytest

from engine import prompts, review, script
from engine.story import DRIFT_PHRASES, load
from pathlib import Path

STORIES = Path(__file__).resolve().parent.parent / "stories"
BOTH = {"left": True, "right": True, "faces": 2}
ONLY_LEFT = {"left": True, "right": False, "faces": 1}
NONE = {"left": False, "right": False, "faces": 0}
STABLE = [3.0, 2.5, 2.8]


def test_establish_take_with_both_faces_and_stable_ending_is_accepted():
    assert review.establish_problems([], STABLE, [BOTH, BOTH, BOTH]) == []


def test_establish_rejected_for_a_missing_face():
    bad = review.establish_problems([], STABLE, [ONLY_LEFT, ONLY_LEFT, ONLY_LEFT])
    assert bad and "right" in bad[0]
    assert review.establish_problems([], STABLE, [ONLY_LEFT, BOTH, NONE])  # right seen in only 1 of 3 frames
    assert review.establish_problems([], STABLE, [BOTH, BOTH, ONLY_LEFT]) == []  # 2 of 3 is enough


@pytest.mark.parametrize("unknown", [None, [], "boom", [{"left": True}], {}])
def test_unknown_face_result_fails_closed(unknown):
    bad = review.establish_problems([], STABLE, unknown)
    assert bad and "could not be judged" in bad[0]


def test_face_check_that_cannot_run_returns_none(tmp_path):
    assert review.find_faces([tmp_path / "a.png"], python=str(tmp_path / "no_such_python")) is None


def test_establish_rejects_cuts_and_an_unstable_ending():
    assert any("cut inside" in p for p in review.establish_problems([84], STABLE, [BOTH] * 3))
    bad = review.establish_problems([], [40.0, 41.0, 42.0], [BOTH] * 3)
    assert any("not stable" in p for p in bad)
    assert any("failing closed" in p for p in review.establish_problems([], [1.0, 2.0], [BOTH] * 3))  # too few samples to judge


def test_establish_stability_uses_the_existing_drift_measure():
    ref = np.zeros((96, 168, 3), np.float32)
    frames = np.stack([np.full((96, 168, 3), v, np.float32) for v in (5, 6, 5)])
    assert review.establish_problems([], review.drift_diffs(frames, ref), [BOTH] * 3) == []


# ---- speech model ----------------------------------------------------------------------------------------------

def test_pauses_are_internal_punctuation_only():
    assert script.pause_count("师傅，今晚还开船吗？") == 1
    assert script.pause_count("傻孩子，那几个包子，早就请你了。") == 2
    assert script.pause_count("我是当年门口那个偷包子的小孩。") == 0
    assert script.pause_count("师傅，@{ask}今晚还开船吗？") == 1


def test_speech_model_and_conservative_estimate():
    line = "傻孩子，那几个包子，早就请你了。"  # 13 characters, 2 pauses, measured 4.00 s
    assert script.speech_seconds(line) == pytest.approx(13 / 4.55 + 2 * 0.72)
    assert script.speech_seconds_safe(line) == pytest.approx(script.speech_seconds(line) + 0.75)


# (text, measured seconds from first to last heard word) from earlier test renders
MEASURED = [("阿姨，这碗面的味道，我找了二十年。", 4.30), ("你是谁？我不认识你。", 2.78), ("我是当年门口那个偷包子的小孩。", 2.92),
            ("是你！你知不知道我找了你多久！", 4.28), ("对不起，我回来还钱了。", 3.18), ("傻孩子，那几个包子，早就请你了。", 4.00),
            ("师傅，今晚还开船吗？", 2.62), ("这么大的雨，你去对岸做什么？", 2.70), ("我爸在那边，等了我十年了。", 3.02),
            ("上船吧，我送你过去。", 2.74), ("这么大的雨，你到对岸去找谁？", 3.32)]


def test_conservative_span_covers_every_measured_line():
    for text, seconds in MEASURED:
        assert script.speech_seconds_safe(text) >= seconds, text


def test_clip_is_long_enough_for_late_onset_slow_speech_and_the_closing_floor():
    for text, seconds in MEASURED:
        for first in (True, False):
            frames = script.clip_length(text, first)
            head = 0.0 if first else script.HEAD_FRAMES / script.FPS
            worst_end = head + script.ONSET_MAX + seconds
            assert frames / script.FPS - worst_end >= script.MIN_CLOSING_SILENCE, (text, first, frames)
            assert frames % 17 == 5


def test_the_floor_is_one_number_shared_by_length_prompt_and_gate():
    assert review.MIN_CLOSING_SILENCE == script.MIN_CLOSING_SILENCE == 0.5


def test_new_lengths_for_the_shipped_stories():
    ferry = load(str(STORIES / "ferry.json"), [])
    noodle = load(str(STORIES / "noodle.json"), [])
    assert [script.clip_length(s["line"], i == 0) for i, s in enumerate(ferry["segments"])] == [141, 175, 175, 158]
    assert [script.clip_length(s["line"], i == 0) for i, s in enumerate(noodle["segments"])] == [175, 158, 175, 175, 158, 192]


def test_the_noodle_line_that_ran_out_of_room_now_gets_room():
    line = "阿姨，这碗面的味道，我找了二十年。"  # take 1 of the regression ran 141 frames and ended 0.445 s before the clip end
    assert script.clip_length(line, True) > 141


# ---- prompts ---------------------------------------------------------------------------------------------------

@pytest.fixture
def ferry():
    return load(str(STORIES / "ferry.json"), [])


def test_establish_prompt_is_silent_and_pins_screen_positions(ferry):
    p = prompts.establish_prompt(ferry, 124)
    assert "<d>" not in p and "<Audio" not in p and "Mandarin" not in p
    assert "<Picture 1>" in p and "<Picture 2>" in p
    assert "screen-left" in p and "screen-right" in p and "side profile" in p
    assert "no subtitles" in p.lower()
    assert not any(pat.search(p) for pat in DRIFT_PHRASES)


def test_first_segment_uses_the_two_shot_and_opens_the_scene(ferry):
    seg = ferry["segments"][0]
    first = prompts.segment_prompt(ferry, seg, 141, True)
    later = prompts.segment_prompt(ferry, seg, 141, False)
    assert "<Picture 2>" not in first and "<Picture 1>" in first
    assert "Opening the scene" in first and "Seamlessly continuing" in later
    assert first.count("<d>[Mandarin]师傅，今晚还开船吗？</d>") == 1


def test_prompt_timecodes_agree_with_clip_length_and_floor(ferry):
    for i, seg in enumerate(ferry["segments"]):
        length = script.clip_length(seg["line"], i == 0)
        t0 = (0.0 if i == 0 else script.HEAD_FRAMES / script.FPS) + script.LEAD_IN
        t1 = t0 + prompts.planned_seconds(seg["line"])
        assert t1 <= length / script.FPS - script.MIN_CLOSING_SILENCE
