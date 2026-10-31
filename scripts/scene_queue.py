#!/usr/bin/env python3
"""The shared job queue for the scene workers. Plain directories, so any number of worker scripts can use it at once.

    scene_queue.py init                   build scene_queue/jobs.json from scenes/scenes.json
    scene_queue.py claim <worker>           print a job name, WAIT (jobs remain but none can start yet) or EMPTY (nothing left)
    scene_queue.py args <job>             the arguments for render_job.py
    scene_queue.py needs <job>            files (relative to the project) the job needs on the box
    scene_queue.py done <job>             mark done, drop the lock
    scene_queue.py fail <job> <reason>    first failure: back in the queue. Second failure: marked failed with both reasons
    scene_queue.py release <job>          the box vanished: drop the lock without counting a failure
    scene_queue.py status                 one line per state

A claim is os.mkdir(lock/<job>), which either creates the directory or fails, so two workers can never hold the same job.
WORKER_QUEUE_DIR and WORKER_ROOT move the queue and the project root (the tests use temporary ones).
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("WORKER_ROOT", Path(__file__).resolve().parent.parent))
Q = Path(os.environ.get("WORKER_QUEUE_DIR", ROOT / "scene_queue"))
MAX_FAILURES = 2


def seconds_for(frames: int) -> float:
    """Sampling seconds for one clip. Fitted on the three clip lengths measured on disk (124, 141, 158 frames, official weights):
    t = 30.6 + 0.00939 * frames^2. Beyond 158 frames this is an extrapolation, and the Singularity int8 stack is not measured at all."""
    return 30.6 + 0.00939 * frames * frames


def build_jobs(defs: dict) -> list:
    jobs = []
    voice_files = [a["file"] for a in defs["assets"].values() if a["producer"] == "v9_voiceseed"]
    jobs.append({"name": "v9_voiceseed", "args": "v9_voiceseed", "needs": [defs["assets"]["author_linwei"]["file"], defs["assets"]["author_chenmo"]["file"]],
                 "produces": voice_files, "est": seconds_for(124) + seconds_for(141) + 60, "group": "asset"})
    for c in defs["casts"]:
        jobs.append({"name": c["id"], "args": c["id"], "needs": [], "produces": [defs["assets"][c["asset"]]["file"]], "est": seconds_for(124) + 30, "group": "asset"})
    v9 = defs["v9"]
    v9_needs = [defs["assets"][k]["file"] for k in ("author_linwei", "author_chenmo", "author_linwei_profile", "author_taillock", "author_linwei_voice", "author_chenmo_voice")]
    for seed in v9["seeds"]:
        jobs.append({"name": f"v9__{seed}", "args": f"v9 {seed}", "needs": v9_needs, "produces": [], "est": sum(seconds_for(f) for f in (124, 141, 141, 141)) + 60, "group": "v9"})
    for s in defs["scenes"]:
        needs = sorted({defs["assets"][a]["file"] for c in s["clips"] for a in c["refs"] + ([c["voice"]] if c["voice"] else [])})
        for seed in s["seeds"]:
            jobs.append({"name": f"{s['id']}__{seed}", "args": f"{s['id']} {seed}", "needs": needs, "produces": [], "est": sum(seconds_for(c["frames"]) for c in s["clips"]) + 40,
                         "group": s["id"]})
    jobs.sort(key=lambda j: (j["group"] != "asset", -j["est"]))  # assets first, then the longest jobs first so the last job to finish is short
    return jobs


def load() -> list:
    return json.loads((Q / "jobs.json").read_text(encoding="utf-8"))


def state(name: str) -> str:
    if (Q / "done" / name).exists():
        return "done"
    if (Q / "failed" / f"{name}.json").exists():
        return "failed"
    if (Q / "lock" / name).exists():
        return "running"
    return "open"


def ready(job: dict) -> bool:
    return all((ROOT / f).exists() for f in job["needs"])


def claim(worker: str) -> str:
    jobs = load()
    for job in jobs:
        if state(job["name"]) != "open":
            continue
        if not ready(job):
            continue
        try:
            os.mkdir(Q / "lock" / job["name"])
        except FileExistsError:
            continue
        (Q / "lock" / job["name"] / "owner").write_text(f"{worker} {time.strftime('%H:%M:%S')}", encoding="utf-8")
        return job["name"]
    # Something is still running, so an asset it makes may unblock a waiting job. If nothing is running and nothing can start, the rest can never run.
    return "WAIT" if any(state(j["name"]) == "running" for j in jobs) else "EMPTY"


def unlock(name: str) -> None:
    lock = Q / "lock" / name
    if lock.exists():
        for f in lock.iterdir():
            f.unlink()
        lock.rmdir()


def main() -> int:
    cmd, rest = sys.argv[1], sys.argv[2:]
    for d in ("lock", "done", "failed", "tries"):
        (Q / d).mkdir(parents=True, exist_ok=True)
    if cmd == "init":
        defs = json.loads((ROOT / "scenes" / "scenes.json").read_text(encoding="utf-8"))
        jobs = build_jobs(defs)
        (Q / "jobs.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
        print(f"{len(jobs)} jobs, {sum(j['est'] for j in jobs) / 60:.0f} estimated GPU minutes")
    elif cmd == "claim":
        print(claim(rest[0]))
    elif cmd in ("args", "needs"):
        job = next(j for j in load() if j["name"] == rest[0])
        print(job["args"] if cmd == "args" else "\n".join(job["needs"]))
    elif cmd == "done":
        (Q / "done" / rest[0]).write_text(time.strftime("%H:%M:%S"), encoding="utf-8")
        unlock(rest[0])
    elif cmd == "release":
        unlock(rest[0])
    elif cmd == "fail":
        name, reason = rest[0], " ".join(rest[1:])[:1500]
        tries = Q / "tries" / f"{name}.json"
        reasons = json.loads(tries.read_text(encoding="utf-8")) if tries.exists() else []
        reasons.append(reason)
        tries.write_text(json.dumps(reasons, ensure_ascii=False), encoding="utf-8")
        if len(reasons) >= MAX_FAILURES:
            (Q / "failed" / f"{name}.json").write_text(json.dumps({"job": name, "reasons": reasons}, ensure_ascii=False, indent=1), encoding="utf-8")
        unlock(name)
    elif cmd == "status":
        jobs = load()
        counts = {}
        for j in jobs:
            counts[state(j["name"])] = counts.get(state(j["name"]), 0) + 1
        print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
