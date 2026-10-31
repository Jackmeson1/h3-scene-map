"""Gates on synthetic data: drift, dialogue, negation, closing silence."""
import numpy as np

from engine import review


def words(text, start=0.5, per=0.25):
    return [{"word": c, "start": start + i * per, "end": start + (i + 1) * per} for i, c in enumerate(text)]


def frames(values, shape=(96, 168, 3)):
    return np.stack([np.full(shape, v, np.float32) for v in values])


REF = np.zeros((96, 168, 3), np.float32)


def test_drift_gate_flags_three_in_a_row():
    diffs = review.drift_diffs(frames([0, 10, 40, 40, 40, 0]), REF)
    out = review.drift_verdict(diffs)
    assert out and "1.0s" in out[0]  # the run starts at sample 2 = 1.0 s at 2 Hz


def test_drift_gate_needs_three_consecutive_samples():
    assert review.drift_verdict(review.drift_diffs(frames([40, 40, 0, 40, 40, 0]), REF)) == []


def test_drift_gate_threshold_is_strictly_above_35():
    assert review.drift_verdict(review.drift_diffs(frames([35, 35, 35, 35]), REF)) == []
    assert review.drift_verdict(review.drift_diffs(frames([36, 36, 36]), REF))


def test_drift_mask_ignores_caption_band():
    clip = frames([0] * 6)
    clip[:, 80:, :, :] = 255.0  # a burned-in caption band, the bottom 17 percent
    assert review.drift_verdict(review.drift_diffs(clip, REF, 0.0)) != []
    assert review.drift_verdict(review.drift_diffs(clip, REF, 0.2)) == []


def test_dialogue_accepts_the_homophone_at_0875():
    s, bad = review.dialogue_verdict("师傅，今晚还开船吗？", words("师父今晚还开船吗"))
    assert s["match"] == 0.875 and bad == []


def test_dialogue_rejects_four_of_eight_characters():
    s, bad = review.dialogue_verdict("上船吧我送你过去", words("上船吧我"))
    assert s["match"] < review.MIN_MATCH and bad


def test_dialogue_rejects_dropped_or_added_negation():
    _, bad = review.dialogue_verdict("我不认识你", words("我认识你"))
    assert any("negation" in p for p in bad)
    s, bad = review.dialogue_verdict("上船吧我送你过去", words("上船吧我不送你过去"))
    assert s["match"] > 0.9 and any("negation" in p for p in bad)  # the ratio alone would have passed it
    assert review.dialogue_verdict("我不认识你", words("我不认识你"))[1] == []


def test_dialogue_ignores_punctuation_and_anchors():
    assert review.dialogue_verdict("师傅，@{ask}今晚还开船吗？", words("师傅今晚还开船吗"))[1] == []


def test_empty_transcript_is_rejected():
    assert review.dialogue_verdict("你好吗", [])[1]


def test_closing_silence_gate():
    assert review.silence_verdict(words("你好吗", 0.5, 1.0), 5.0) == []  # speech ends at 3.5, 1.5 s left
    assert review.silence_verdict(words("你好吗", 0.5, 1.5), 5.0)  # ends at 5.0
    assert review.silence_verdict(words("你好", 0.5, 2.05), 5.0)  # ends at 4.6, 0.4 s left
    assert review.silence_verdict(words("你好", 0.5, 2.0), 5.0) == []  # 0.5 s left is the floor, not under it


def test_judge_take_collects_every_problem():
    clip_words = words("上船吧我送你过去", 0.5, 0.6)  # ends at 5.3
    diffs = review.drift_diffs(frames([40, 40, 40]), REF)
    _, bad = review.judge_take("上船吧我不送你过去", clip_words, [84], diffs, 5.5)
    joined = " ".join(bad)
    assert "cut inside" in joined and "framing drifted" in joined and "negation" in joined and "closing" in joined or "closed-mouth" in joined
