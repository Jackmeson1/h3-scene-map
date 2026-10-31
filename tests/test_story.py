"""Lint and schema, in both directions, plus the shipped stories."""
import copy
from pathlib import Path

import pytest

from engine import comfy
from engine.story import lint, load

STORIES = Path(__file__).resolve().parent.parent / "stories"


@pytest.fixture
def story():
    return load(str(STORIES / "ferry.json"), [])


@pytest.mark.parametrize("name", ["ferry", "noodle"])
def test_shipped_stories_pass(name):
    assert lint(load(str(STORIES / f"{name}.json"), [])) == []


def errors_with(story, **edit):
    s = copy.deepcopy(story)
    for path, value in edit.items():
        node = s
        parts = path.split("__")
        for p in parts[:-1]:
            node = node[int(p)] if isinstance(node, list) else node[p]
        last = parts[-1]
        if value is None:
            del node[int(last) if isinstance(node, list) else last]
        else:
            node[int(last) if isinstance(node, list) else last] = value
    return lint(s)


def test_missing_required_fields_are_rejected(story):
    assert any("'scene'" in e for e in errors_with(story, scene=None))
    assert any("'seed'" in e for e in errors_with(story, seed="x"))
    assert any("characters.left.voice" in e for e in errors_with(story, characters__left__voice=None))
    assert any("segment 1" in e and "'delivery'" in e for e in errors_with(story, segments__0__delivery=None))
    assert any("'segments'" in e for e in errors_with(story, segments=[]))


def test_overlay_schema(story):
    assert any("unknown" in e for e in errors_with(story, overlays__0__type="sparkle"))
    assert any("title needs" in e for e in errors_with(story, overlays__2__text=None))
    assert any("who" in e for e in errors_with(story, overlays__0__who=None))
    assert any("'lasts'" in e for e in errors_with(story, overlays__0__lasts=-1))
    assert any("unknown anchor" in e for e in errors_with(story, overlays__0__at="nowhere"))
    assert any("name is required" in e for e in errors_with(story, characters__left__name=None))


def test_reserved_anchor_names_are_rejected(story):
    assert any("reserved" in e for e in errors_with(story, segments__0__line="师傅，@{start}今晚还开船吗？"))


def test_model_length_limits(story):
    assert any("outside" in e for e in errors_with(story, segments__1__length=5 + 17 * 20))
    assert any("5 + 17k" in e for e in errors_with(story, segments__1__length=150))
    assert any("too short" in e for e in errors_with(story, segments__1__length=141))  # needs 158 for that line


def test_cast_line_must_fit_the_casting_clip(story):
    assert any("cast_line" in e for e in errors_with(story, characters__left__cast_line="我叫小禾，从南边来，想过河去看看，" * 3))


def test_fixed_false_positive_is_gone(story):
    ok = "breathing hard with her chest rising and falling, while the other watches"
    assert errors_with(story, segments__0__after=ok) == []
    assert errors_with(story, segments__0__after="she feels a rising sense of dread") == []


@pytest.mark.parametrize("phrase", ["he turns her head toward the river", "she turns away from him", "he rises from the bench",
                                    "she stands up", "he sits down", "she walks out of the frame", "he rotates his body"])
def test_body_leaving_or_head_rotating_is_rejected(story, phrase):
    assert any("segments" in e or "segment 1" in e for e in errors_with(story, segments__0__before=phrase)), phrase


def test_camera_word_alone_is_fine_but_moves_are_not(story):
    s = copy.deepcopy(story)
    s["segments"][1]["line"] = "@{reply}这么大的雨，你去对岸做什么？"
    tag = "<d>[Mandarin]这么大的雨，你去对岸做什么？</d>"
    s["segments"][1]["prompt"] = f"The camera is locked off. The camera stays here. {tag} no subtitles"
    assert lint(s) == []
    s["segments"][1]["prompt"] = f"The camera slowly zooms in. {tag} no subtitles"
    assert any("camera movement" in e for e in lint(s))


def test_forbidden_movement_in_a_prompt_override_is_caught(story):
    s = copy.deepcopy(story)
    tag = "<d>[Mandarin]这么大的雨，你去对岸做什么？</d>"
    s["segments"][1]["line"] = "@{reply}这么大的雨，你去对岸做什么？"
    s["segments"][1]["prompt"] = f"She turns her head toward him. {tag} no subtitles"
    assert any("segment 2.prompt" in e for e in lint(s))


def test_engine_check_names_every_difference():
    found = {"comfy": comfy.ENGINE["comfy"], "motion_context": "deadbeef", "comfy_dirty": False, "motion_context_dirty": True,
             "weights": {"a.safetensors": 10, "b.safetensors": None, "c.safetensors": 5, "d.safetensors": 7}}
    lock = {"weights": {"a.safetensors": 10, "c.safetensors": 6}}
    text = " | ".join(comfy.engine_problems(found, lock))
    assert "motion_context is at deadbeef" in text and "modified tracked files" in text
    assert "b.safetensors is missing" in text and "c.safetensors is 5 bytes, pinned 6" in text and "d.safetensors has no pinned size" in text
    assert "a.safetensors" not in text
    good = {"comfy": comfy.ENGINE["comfy"], "motion_context": comfy.ENGINE["motion_context"], "comfy_dirty": False, "motion_context_dirty": False,
            "weights": {"a.safetensors": 10}}
    assert comfy.engine_problems(good, {"weights": {"a.safetensors": 10}}) == []
