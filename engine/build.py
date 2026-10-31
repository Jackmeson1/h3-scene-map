"""Content-addressed steps: a step reruns only when something it depends on, or the code that defines it, changed.

A step's key hashes its parameters, the source files that define its behaviour (its recipe), and the keys of its
dependencies, so a change anywhere invalidates exactly the steps downstream of it. Segment N depends on segment N-1,
which is what makes editing a middle segment re-render the segments after it instead of leaving a stale seam.

A step counts as done only when its done.json parses, carries the same key, and lists a manifest (size and sha256) that
every declared output still matches. Anything else wipes the step directory and runs it again from empty.
"""

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

CCU_PER_HOUR = 10.05  # measured on a Colab G4
MARKER = "done.json"
SCHEMA = 2
ENGINE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Step:
    name: str
    key: str
    dir: Path
    outputs: tuple = ()


def source_digest(names) -> str:
    """Hash of the named engine source files, line endings normalised so a Windows upload and a Linux checkout agree."""
    h = hashlib.sha256()
    for name in sorted(names):
        h.update(name.encode())
        h.update((ENGINE_DIR / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_manifest(directory: Path, outputs) -> dict:
    manifest = {}
    for rel in outputs:
        path = directory / rel
        if not path.is_file():
            raise FileNotFoundError(f"required output '{rel}' was not produced in {directory.name}")
        manifest[rel] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    return manifest


def write_marker(path: Path, payload: dict) -> None:
    """Temp file, flush, fsync, rename: a crash leaves either no marker or a whole one."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_marker(step: Step) -> dict:
    return json.loads((step.dir / MARKER).read_text(encoding="utf-8"))


def check_step(step: Step) -> Optional[str]:
    """None when the step directory holds a complete, intact result. Otherwise the reason it cannot be reused."""
    marker = step.dir / MARKER
    if not marker.exists():
        return None if not step.dir.exists() else "no marker"
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"marker unreadable: {exc.__class__.__name__}"
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return "marker has the wrong schema"
    if data.get("key") != step.key:
        return "marker key does not match the step"
    manifest = data.get("manifest")
    if not isinstance(manifest, dict) or set(manifest) != set(step.outputs):
        return "manifest does not list the required outputs"
    for rel, want in manifest.items():
        path = step.dir / rel
        if not path.is_file():
            return f"output '{rel}' is missing"
        if path.stat().st_size != want.get("size"):
            return f"output '{rel}' has the wrong size"
        if sha256_file(path) != want.get("sha256"):
            return f"output '{rel}' fails its sha256"
    return None


class Build:
    def __init__(self, root: Path, plan_only: bool = False):
        self.root = root
        self.plan_only = plan_only
        self.rows: list[dict] = []
        self.rebuilt: set[str] = set()  # keys of steps that ran, or would run, in this build despite an existing directory

    def step(self, name: str, params: dict, deps: list[Step], run: Callable[[Step], Optional[dict]],
             outputs=(), recipe=(), estimate: float = 2.0, gpu: bool = False) -> Step:
        kind = name.rstrip("0123456789")
        blob = json.dumps([kind, params, [d.key for d in deps], source_digest(recipe), list(outputs)], sort_keys=True, ensure_ascii=False)
        key = hashlib.sha256(blob.encode()).hexdigest()[:16]
        step = Step(name, key, self.root / f"{name}-{key}", tuple(outputs))
        reason = check_step(step)
        marker_exists = (step.dir / MARKER).exists()
        if reason is None and marker_exists and any(d.key in self.rebuilt for d in deps):
            reason = "an upstream step was rebuilt, so this result is stale"
        if reason is None and marker_exists:
            self.rows.append({"step": name, "state": "keep", "seconds": 0.0, "gpu": gpu, "note": ""})
            return step
        if step.dir.exists():
            self.rebuilt.add(step.key)
        note = f"INVALID: {reason}" if reason else ""
        if self.plan_only:
            self.rows.append({"step": name, "state": "run", "seconds": estimate, "gpu": gpu, "note": note})
            if note:
                self.rebuilt.add(step.key)
            return step
        if step.dir.exists():
            shutil.rmtree(step.dir)  # a rerun starts from an empty directory
        step.dir.mkdir(parents=True)
        t0 = time.time()
        try:
            meta = run(step) or {}
            manifest = make_manifest(step.dir, outputs)
        except BaseException:
            self.rows.append({"step": name, "state": "FAILED", "seconds": round(time.time() - t0, 1), "gpu": gpu, "note": ""})
            raise  # no marker: the directory and its takes stay for inspection
        seconds = round(time.time() - t0, 1)
        write_marker(step.dir / MARKER, {"schema": SCHEMA, "step": name, "key": key, "seconds": seconds,
                                         "manifest": manifest, "meta": meta})
        self.rows.append({"step": name, "state": "run", "seconds": seconds, "gpu": gpu, "note": note})
        return step

    def summary(self) -> str:
        lines = [f"{r['state'].upper():<6}{r['step']:<14}{r['seconds']:>8.0f}s  {r.get('note', '')}".rstrip() for r in self.rows]
        gpu = sum(r["seconds"] for r in self.rows if r["gpu"] and r["state"] == "run")
        kept = sum(1 for r in self.rows if r["state"] == "keep")
        invalid = sum(1 for r in self.rows if r.get("note"))
        verb = "estimated" if self.plan_only else "spent"
        lines.append(f"{kept} of {len(self.rows)} steps reused; {verb} {gpu / 60:.1f} GPU minutes, {gpu / 3600 * CCU_PER_HOUR:.2f} CCU"
                     + (f"; {invalid} step(s) have an invalid or stale result and will be rebuilt" if invalid else ""))
        return "\n".join(lines)
