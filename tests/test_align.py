"""Timing: clamps, monotonic times, flags for guessed characters, anchors, total duration."""
from engine import align


def words(text, start, per=0.25):
    return [{"word": c, "start": start + i * per, "end": start + (i + 1) * per} for i, c in enumerate(text)]


def test_times_are_clamped_into_the_clip():
    # the first character was not heard, and the extrapolation before 0.05 s would go negative
    chars, info = align.script_times("你好吗", [{"word": "好吗", "start": 0.05, "end": 0.25}], (0.3, 1.0), dur=5.0)
    assert all(c[1] >= 0 and c[2] >= c[1] for c in chars)
    chars_hi, _ = align.script_times("你好吗", [{"word": "你好", "start": 4.9, "end": 5.3}], (0.3, 1.0), dur=5.0)
    assert max(c[2] for c in chars_hi) <= 5.0


def test_times_never_go_backwards():
    chars, _ = align.script_times("你好吗我是谁", words("你好吗我是谁", 1.0), (0.3, 3.0), dur=5.0)
    starts = [c[1] for c in chars]
    assert starts == sorted(starts)
    assert align.clamp_times([(2.0, 3.0), (1.0, 1.5), (0.5, 0.2)], 10) == [(2.0, 3.0), (2.0, 2.0), (2.0, 2.0)]


def test_extrapolated_characters_are_flagged():
    _, info = align.script_times("师傅今晚", words("师父今晚", 1.0), (0.3, 3.0), dur=5.0)  # 傅 vs 父
    assert info["extrapolated"] == 1 and info["source"] == ["heard", "extrapolated", "heard", "heard"]
    assert info["fallback"] is False


def test_nothing_heard_is_a_flagged_fallback():
    chars, info = align.script_times("你好吗", [], (0.3, 3.3), dur=5.0)
    assert info["fallback"] is True and info["extrapolated"] == 3 and set(info["source"]) == {"fallback"}
    assert chars[0][1] == 0.3


def test_anchor_lands_on_next_character_and_reports_how():
    chars, info = align.script_times("上船吧我送你", words("上船吧我送你", 1.0), (0.3, 3.0), dur=5.0)
    times, how = align.anchor_times("上船吧@{x}我送你", chars, info["source"])
    assert times["x"] == chars[3][1] and how["x"] == "heard"


def story(lines):
    return {"segments": [{"speaker": "left", "line": l} for l in lines]}


def test_anchor_moves_with_the_word_and_offsets_use_clip_durations():
    a = align.build_timing(story(["你好吗", "@{k}我很好"]), [(5.0, words("你好吗", 1.0)), (5.0, words("我很好", 1.0))])
    b = align.build_timing(story(["你好吗", "@{k}我很好"]), [(5.0, words("你好吗", 1.0)), (5.0, words("我很好", 2.0))])
    assert a["anchors"]["k"] == 6.0 and b["anchors"]["k"] == 7.0
    assert a["clips"][1]["start"] == 5.0 and a["anchors"]["end"] == 10.0


def test_total_duration_comes_from_the_master_and_the_gap_is_recorded():
    t = align.build_timing(story(["你好吗"]), [(5.0, words("你好吗", 1.0))], master_duration=5.04)
    assert t["duration"] == 5.04 and t["anchors"]["end"] == 5.04
    assert t["duration_check"] == {"clip_sum": 5.0, "master": 5.04, "delta": 0.04}


def test_segments_with_guessed_characters_are_listed():
    t = align.build_timing(story(["你好吗", "我很好"]), [(5.0, words("你好吗", 1.0)), (5.0, [])])
    assert t["segments_with_unheard_characters"] == [2]
    assert t["segments"][1]["fallback"] is True


def test_closing_silence_is_recorded_per_segment():
    t = align.build_timing(story(["你好吗"]), [(5.0, words("你好吗", 1.0))])
    assert t["segments"][0]["closing_silence"] == 4.0 - 0.75 + 0.0 or abs(t["segments"][0]["closing_silence"] - 3.25) < 1e-6
