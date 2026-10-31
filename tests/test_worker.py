"""The shared queue and the worker loop, with a fake bringup and a fake runner. No Colab, no network."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def project(tmp_path, jobs, needs_file=None):
    """A throwaway project tree holding copies of the worker scripts and a queue with the given jobs."""
    (tmp_path / "scripts").mkdir()
    for name in ("worker.sh", "scene_queue.py"):
        shutil.copy2(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    q = tmp_path / "scene_queue"
    for d in ("lock", "done", "failed", "tries"):
        (q / d).mkdir(parents=True)
    rows = [{"name": j, "args": j, "needs": [needs_file] if (needs_file and j == "needy") else [], "produces": [], "est": 1, "group": "g"} for j in jobs]
    (q / "jobs.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "bringup.sh").write_text('#!/usr/bin/env bash\necho x >> "$(dirname "$0")/bringups.log"\nexit 0\n')
    (tmp_path / "runner.sh").write_text(
        '#!/usr/bin/env bash\n'
        'here=$(dirname "$0"); job=$2\n'
        'echo "$1 $job" >> "$here/ran.log"\n'
        'case "$job" in\n'
        '  bad*) echo "boom in $job"; exit 1 ;;\n'
        '  vanish_once*) if [ ! -f "$here/vanished" ]; then touch "$here/vanished"; exit 10; fi; exit 0 ;;\n'
        '  vanish_always*) exit 10 ;;\n'
        '  *) sleep 0.3; exit 0 ;;\n'
        'esac\n')
    return tmp_path


def env(root):
    e = dict(os.environ, WORKER_ROOT=str(root), WORKER_QUEUE_DIR=str(root / "scene_queue"), WORKER_BRINGUP=str(root / "bringup.sh"), WORKER_RUNNER=str(root / "runner.sh"),
             WORKER_POLL="0.2", PYTHONIOENCODING="utf-8")
    return e


def worker(root, session):
    return subprocess.Popen([BASH, str(root / "scripts" / "worker.sh"), session, "5"], env=env(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def q(root, *args):
    return subprocess.run([sys.executable, str(root / "scripts" / "scene_queue.py"), *args], env=env(root), capture_output=True, text=True).stdout.strip()


def test_claim_is_exclusive_and_a_taken_job_is_not_offered_again(tmp_path):
    root = project(tmp_path, ["a", "b"])
    assert q(root, "claim", "L1") == "a"
    assert q(root, "claim", "L2") == "b"
    assert q(root, "claim", "L3") == "WAIT"  # everything is running, nothing left to start
    q(root, "done", "a")
    q(root, "done", "b")
    assert q(root, "claim", "L3") == "EMPTY"


def test_two_workers_never_run_the_same_job(tmp_path):
    jobs = [f"ok{i}" for i in range(8)]
    root = project(tmp_path, jobs)
    workers = [worker(root, "L1"), worker(root, "L2")]
    for p in workers:
        p.communicate(timeout=60)
    ran = [line.split()[1] for line in (root / "ran.log").read_text().splitlines()]
    assert sorted(ran) == sorted(jobs)  # each exactly once
    assert q(root, "status") == "done=8"
    assert {line.split()[0] for line in (root / "ran.log").read_text().splitlines()} == {"L1", "L2"}  # both workers worked


def test_a_job_that_fails_twice_is_marked_failed_with_its_reasons(tmp_path):
    root = project(tmp_path, ["bad1", "ok1"])
    p = worker(root, "L1")
    p.communicate(timeout=60)
    failed = json.loads((root / "scene_queue" / "failed" / "bad1.json").read_text())
    assert len(failed["reasons"]) == 2 and "boom in bad1" in failed["reasons"][0]
    assert q(root, "status") == "done=1 failed=1"


def test_a_vanished_box_releases_the_job_and_the_vm_is_recreated(tmp_path):
    root = project(tmp_path, ["vanish_once1", "ok1"])
    p = worker(root, "L1")
    p.communicate(timeout=60)
    assert q(root, "status") == "done=2"
    assert len((root / "bringups.log").read_text().splitlines()) == 2  # first VM, then one re-creation
    assert not (root / "scene_queue" / "tries" / "vanish_once1.json").exists()  # a vanished box is not counted as a failure of the job


def test_a_worker_gives_up_after_three_recreations(tmp_path):
    root = project(tmp_path, ["vanish_always1"])
    p = worker(root, "L1")
    out, _ = p.communicate(timeout=60)
    assert p.returncode == 3
    assert len((root / "bringups.log").read_text().splitlines()) == 4  # the first VM and three re-creations
    assert q(root, "status") == "open=1"  # still available to another worker


def test_a_job_waits_for_its_assets_and_runs_once_they_exist(tmp_path):
    root = project(tmp_path, ["producer", "needy"], needs_file="scene_assets/x.wav")
    assert q(root, "claim", "L1") == "producer"
    assert q(root, "claim", "L2") == "WAIT"  # needy cannot start yet, and the producer is still running
    (root / "scene_assets").mkdir()
    (root / "scene_assets" / "x.wav").write_bytes(b"0")
    q(root, "done", "producer")
    assert q(root, "claim", "L2") == "needy"


def test_a_job_whose_asset_will_never_exist_does_not_hang_the_workers(tmp_path):
    root = project(tmp_path, ["needy"], needs_file="scene_assets/never.wav")
    assert q(root, "claim", "L1") == "EMPTY"  # nothing running and nothing startable: stop instead of waiting forever


@pytest.mark.skipif(not (ROOT / "scenes" / "scenes.json").exists(), reason="the scene definitions are not in this repo")
def test_the_real_queue_builds_from_scenes_json(tmp_path):
    shutil.copytree(ROOT / "scenes", tmp_path / "scenes", ignore=shutil.ignore_patterns("assets"))
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "scene_queue.py", tmp_path / "scripts" / "scene_queue.py")
    e = dict(os.environ, WORKER_ROOT=str(tmp_path), WORKER_QUEUE_DIR=str(tmp_path / "scene_queue"))
    out = subprocess.run([sys.executable, str(tmp_path / "scripts" / "scene_queue.py"), "init"], env=e, capture_output=True, text=True).stdout
    jobs = json.loads((tmp_path / "scene_queue" / "jobs.json").read_text())
    assert len(jobs) == 1 + 3 + 3 + 30  # voice seed, three casts, three V9 runs, ten scenes with three seeds each
    assert [j["name"] for j in jobs[:4]][0] == "v9_voiceseed" and all(j["group"] == "asset" for j in jobs[:4])
    assert len({j["name"] for j in jobs}) == len(jobs)
    assert "estimated GPU minutes" in out
