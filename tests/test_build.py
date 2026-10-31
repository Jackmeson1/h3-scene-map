"""Build graph: markers, manifests, recipes, failed gates. No GPU, no network, no ffmpeg."""
import json
import os

import pytest

from engine import build
from engine.build import Build, MARKER, check_step
from engine.review import AcceptanceError, run_takes


def writer(text="x", name="out.txt"):
    def run(step):
        (step.dir / name).write_text(text)
        return {"note": text}
    return run


def make(root, plan=False):
    return Build(root, plan_only=plan)


def test_fresh_step_runs_then_is_reused(tmp_path):
    b = make(tmp_path)
    s = b.step("a", {}, [], writer(), outputs=["out.txt"])
    assert b.rows[-1]["state"] == "run"
    assert (s.dir / MARKER).exists() and not list(s.dir.glob("*.tmp"))
    b2 = make(tmp_path)
    b2.step("a", {}, [], writer("changed-but-never-called"), outputs=["out.txt"])
    assert b2.rows[-1]["state"] == "keep"


def test_truncated_marker_is_rejected_and_rerun_from_empty(tmp_path):
    b = make(tmp_path)
    s = b.step("a", {}, [], writer(), outputs=["out.txt"])
    (s.dir / "stale_leftover.bin").write_text("junk")
    (s.dir / MARKER).write_text('{"schema": 2, "key": "')  # cut off mid-write
    b2 = make(tmp_path)
    seen = {}

    def run(step):
        seen["leftover"] = (step.dir / "stale_leftover.bin").exists()
        seen["empty"] = not any(step.dir.iterdir())
        (step.dir / "out.txt").write_text("again")

    b2.step("a", {}, [], run, outputs=["out.txt"])
    assert b2.rows[-1]["state"] == "run"
    assert seen == {"leftover": False, "empty": True}


def test_missing_artifact_invalidates(tmp_path):
    b = make(tmp_path)
    s = b.step("a", {}, [], writer(), outputs=["out.txt"])
    (s.dir / "out.txt").unlink()
    assert "missing" in check_step(s)
    plan = make(tmp_path, plan=True)
    plan.step("a", {}, [], writer(), outputs=["out.txt"])
    assert plan.rows[-1]["state"] == "run" and plan.rows[-1]["note"].startswith("INVALID")
    assert "invalid" in plan.summary().lower()


def test_manifest_mismatch_same_size_is_caught_by_hash(tmp_path):
    b = make(tmp_path)
    s = b.step("a", {}, [], writer("aaaa"), outputs=["out.txt"])
    (s.dir / "out.txt").write_text("bbbb")  # same size, different bytes
    assert "sha256" in check_step(s)
    (s.dir / "out.txt").write_text("longer than before")
    assert "size" in check_step(s)


def test_marker_must_list_exactly_the_required_outputs(tmp_path):
    b = make(tmp_path)
    s = b.step("a", {}, [], writer(), outputs=["out.txt"])
    data = json.loads((s.dir / MARKER).read_text())
    data["manifest"] = {}
    (s.dir / MARKER).write_text(json.dumps(data))
    assert check_step(s) is not None


def test_step_that_does_not_produce_its_output_fails_and_writes_no_marker(tmp_path):
    b = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        b.step("a", {}, [], lambda step: None, outputs=["out.txt"])
    d = next(tmp_path.glob("a-*"))
    assert not (d / MARKER).exists()


def test_marker_write_is_atomic(tmp_path, monkeypatch):
    target = tmp_path / MARKER

    def boom(src, dst):
        raise OSError("killed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        build.write_marker(target, {"a": 1})
    assert not target.exists()  # never a half-written marker under the real name


def test_recipe_change_invalidates_only_the_steps_that_use_it(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("A = 1\n")
    (src / "b.py").write_text("B = 1\n")
    monkeypatch.setattr(build, "ENGINE_DIR", src)

    def graph(root):
        b = Build(root)
        a = b.step("a", {}, [], writer("a"), outputs=["out.txt"], recipe=["a.py"])
        b.step("down", {}, [a], writer("d"), outputs=["out.txt"])
        b.step("other", {}, [], writer("o"), outputs=["out.txt"], recipe=["b.py"])
        return {r["step"]: r["state"] for r in b.rows}

    root = tmp_path / "cache"
    assert set(graph(root).values()) == {"run"}
    assert set(graph(root).values()) == {"keep"}
    (src / "a.py").write_text("A = 2\n")
    assert graph(root) == {"a": "run", "down": "run", "other": "keep"}
    (src / "b.py").write_text("B = 2\n")
    assert graph(root) == {"a": "keep", "down": "keep", "other": "run"}


def test_line_endings_do_not_change_the_recipe(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_bytes(b"A = 1\nB = 2\n")
    monkeypatch.setattr(build, "ENGINE_DIR", src)
    one = build.source_digest(["a.py"])
    (src / "a.py").write_bytes(b"A = 1\r\nB = 2\r\n")
    assert build.source_digest(["a.py"]) == one


def test_upstream_rebuild_makes_valid_downstream_stale(tmp_path):
    def graph(root):
        b = Build(root)
        a = b.step("a", {}, [], writer("a"), outputs=["out.txt"])
        b.step("down", {}, [a], writer("d"), outputs=["out.txt"])
        return {r["step"]: r["state"] for r in b.rows}

    graph(tmp_path)
    next(tmp_path.glob("a-*")).joinpath("out.txt").unlink()  # upstream result damaged, downstream marker still looks fine
    assert graph(tmp_path) == {"a": "run", "down": "run"}


def test_exhausted_retakes_raise_and_keep_every_take():
    seen = []

    def attempt(n):
        seen.append(n)
        return {"problems": [f"bad {n}"], "n": n}

    with pytest.raises(AcceptanceError) as err:
        run_takes(attempt, 3)
    assert seen == [0, 1, 2]
    assert [t["n"] for t in err.value.takes] == [0, 1, 2]


def test_first_clean_take_wins():
    takes, kept = run_takes(lambda n: {"problems": [] if n == 1 else ["bad"], "n": n}, 3)
    assert kept["n"] == 1 and len(takes) == 2


def test_failed_gate_leaves_no_marker_and_keeps_diagnostics(tmp_path):
    b = make(tmp_path)

    def render(step):
        (step.dir / "take0.mp4").write_text("rejected footage")
        try:
            run_takes(lambda n: {"problems": ["cut"], "n": n}, 3)
        except AcceptanceError as exc:
            (step.dir / "rejected.json").write_text(json.dumps(exc.takes))
            raise

    with pytest.raises(AcceptanceError):
        b.step("seg1", {}, [], render, outputs=["clip.mp4"])
    d = next(tmp_path.glob("seg1-*"))
    assert not (d / MARKER).exists()
    assert (d / "take0.mp4").exists() and (d / "rejected.json").exists()
    assert b.rows[-1]["state"] == "FAILED"
    again = make(tmp_path, plan=True)  # the next build does not treat the leftovers as done
    again.step("seg1", {}, [], render, outputs=["clip.mp4"])
    assert again.rows[-1]["state"] == "run"
