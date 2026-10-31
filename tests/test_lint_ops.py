"""lint_ops.py: every rule against the real bad line from the incident that produced it, and against its fixed form."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lint_ops  # noqa: E402

NOPATH = "export MSYS_NO_PATHCONV=1\n"


def tags(text, name="t.sh", rx_has_timeout=True):
    return {f.rule for f in lint_ops.lint_text(name, text, rx_has_timeout) if f.waived is None}


CASES = [
    # (rule, bad text, fixed text, file name)
    ("background-and-list",
     'started=$(rx "cd /root/h3 && rm -rf scene_out/$job && setsid nohup /root/venv-comfy/bin/python scripts/render_job.py $args > /root/logs/job-$job.log 2>&1 < /dev/null &\nsleep 2; echo started")\n',
     'started=$(rx "cd /root/h3; rm -rf scene_out/$job; setsid nohup /root/venv-comfy/bin/python scripts/render_job.py $args > /root/logs/job-$job.log 2>&1 < /dev/null &\nsleep 2; echo started")\n',
     "t.sh"),
    ("background-redirects",
     'rx "cd /root/h3; setsid nohup python3 make.py story.json &"\n',
     'rx "cd /root/h3; setsid nohup python3 make.py story.json > /root/logs/m.log 2>&1 < /dev/null &"\n',
     "t.sh"),
    ("pgrep-self-match",
     "st=$(rx \"ls /root/h3/scene_out/$job/; pgrep -f 'scripts/render_job.py' > /dev/null && echo RUNNING\")\n",
     "st=$(rx \"ls /root/h3/scene_out/$job/; pgrep -f '[r]ender_job.py' > /dev/null && echo RUNNING\")\n",
     "t.sh"),
    ("tail-n1-success",
     'up() { timeout 180 colab --auth adc upload -s "$session" "$(cygpath -w "$1")" "$2" 2>&1 | tail -n 1 | grep -q Uploaded && return 0; }\n',
     'up() { said=$(timeout 180 colab --auth adc upload -s "$session" "$(cygpath -w "$1")" "$2" 2>&1); case "$said" in *Uploaded*) return 0 ;; esac; }\n',
     "t.sh"),
    ("windows-python-cr",
     'for f in $($Q needs "$job"); do\n  echo "$f"\ndone\n',
     "for f in $($Q needs \"$job\" | tr -d '\\015'); do\n  echo \"$f\"\ndone\n",
     "t.sh"),
    ("msys-path",
     NOPATH + 'Q="python $root/scripts/scene_queue.py"\n',
     NOPATH + 'Q="python $(cygpath -w "$root/scripts/scene_queue.py")"\n',
     "t.sh"),
    ("tr-d-empty",
     "x=$(echo \"$y\" | tr -d '')\n",
     "x=$(echo \"$y\" | tr -d '\\015')\n",
     "t.sh"),
    ("tr-d-bare-cr",
     "x=$(echo \"$y\" | tr -d 'r')\n",
     "x=$(echo \"$y\" | tr -d '\\015')\n",
     "t.sh"),
    ("tr-d-bare-cr",
     "missing=$(echo \"$listing\" | tr -d '\\r' | sed -n 's#^STEP ##p')\n",
     "missing=$(echo \"$listing\" | tr -d '\\015' | sed -n 's#^STEP ##p')\n",
     "t.sh"),
    ("literal-cr",
     "echo one\r\necho two\r\n",
     "echo one\necho two\n",
     "t.sh"),
    ("colab-auth",
     "timeout 40 colab sessions 2>/dev/null\n",
     "timeout 40 colab --auth adc sessions 2>/dev/null\n",
     "t.sh"),
    ("no-timeout",
     "while true; do\n  colab --auth adc usage\n  sleep 60\ndone\n",
     "while true; do\n  timeout 40 colab --auth adc usage\n  sleep 60\ndone\n",
     "worker_x.sh"),
    ("no-timeout",
     "while true; do\n  curl -s https://example.com/status\n  sleep 60\ndone\n",
     "while true; do\n  curl -s --max-time 20 https://example.com/status\n  sleep 60\ndone\n",
     "worker_x.sh"),
    ("rm-rf-glob",
     'rm -rf "$root"/scene_results/*\n',
     'rm -rf "$root/scene_results/$job"\n',
     "t.sh"),
    ("pgrep-self-match",
     "powershell.exe -Command \"Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'scripts/worker' } | ForEach-Object { Stop-Process -Id $_.ProcessId }\"\n",
     "powershell.exe -Command \"Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '[s]cripts/worker' } | ForEach-Object { Stop-Process -Id $_.ProcessId }\"\n",
     "t.sh"),
    ("exit-status",
     'out=$("$runner" "$session" "$job" | tail -n 2)\ncode=$?\n',
     'out=$("$runner" "$session" "$job")\ncode=$?\n',
     "t.sh"),
    ("exit-status",
     '"$runner" "$session" "$job" || true\n',
     '"$runner" "$session" "$job"\n',
     "t.sh"),
    ("exit-status",
     "trap 'kill $child; exit 0' TERM\n",
     "trap 'kill $child; exit 143' TERM\n",
     "t.sh"),
    ("timeout-function",
     'rx() { echo hi; }\ntimeout 30 rx "ls"\n',
     'rx() { echo hi; }\nrx "ls"\n',
     "t.sh"),
    ("no-pkill-locally",
     "pkill -f worker.sh\n",
     'rx "pkill -f [l]ane.sh"\n',
     "t.sh"),
    ("pgrep-self-match",
     "ps aux | grep render_job.py\n",
     "ps aux | grep [r]ender_job.py\n",
     "t.sh"),
]


@pytest.mark.parametrize("rule,bad,fixed,name", CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_bad_line_is_flagged_and_its_fix_passes(rule, bad, fixed, name):
    assert rule in tags(bad, name), f"{rule} not flagged in: {bad!r}"
    assert rule not in tags(fixed, name), f"{rule} still flagged in the fixed form: {fixed!r}"


def test_fixed_forms_are_clean_as_a_whole():
    for rule, bad, fixed, name in CASES:
        assert tags(fixed, name) == set() or all(t != rule for t in tags(fixed, name)), (rule, fixed)


def test_background_and_list_is_only_flagged_when_it_goes_to_a_background_job():
    assert "background-and-list" not in tags("cd /tmp && make && ls\n")
    assert "background-and-list" not in tags("a && b && c\n")


def test_pgrep_without_f_and_with_variables_is_not_flagged():
    assert "pgrep-self-match" not in tags('pgrep worker > /dev/null\n')
    assert "pgrep-self-match" not in tags('pgrep -f "$pattern" > /dev/null\n')
    assert "pgrep-self-match" not in tags("pgrep -f '[p]ipeline.py|[m]ake.py' > /dev/null\n")


def test_single_assigned_values_from_windows_python_are_not_flagged():
    assert "windows-python-cr" not in tags('args=$($Q args "$job")\n')
    assert "windows-python-cr" not in tags('est=$(python -c "print(1)")\n')


def test_remote_python_is_not_confused_with_windows_python():
    t = NOPATH + 'rx "cd /root/preempt; setsid nohup python3 preempt_box.py $deadline > /dev/null 2>&1 < /dev/null &"\n'
    assert tags(t) == set()
    assert "msys-path" not in tags(NOPATH + 'rx "/root/venv-comfy/bin/python scripts/render_job.py $args"\n')


def test_colab_in_an_echo_or_comment_is_not_flagged():
    assert tags("# colab sessions lists them\n") == set()
    assert tags('echo "run colab sessions to see"\n') == set()


def test_workers_need_timeouts_but_one_shot_scripts_do_not():
    assert "no-timeout" not in tags("colab --auth adc usage\n", "oneshot.sh")


def test_rx_without_its_own_timeout_is_flagged_in_a_worker():
    text = 'while true; do\n  rx "ls"\n  sleep 5\ndone\n'
    assert "no-timeout" in tags(text, "worker_x.sh", rx_has_timeout=False)
    assert "no-timeout" not in tags(text, "worker_x.sh", rx_has_timeout=True)


def test_python_files_that_build_remote_shell_are_checked():
    bad = 'cmd = "cd /root/h3 && rm -rf out && setsid nohup python3 job.py > log 2>&1 < /dev/null &"\n'
    assert "background-and-list" in tags(bad, "builder.py")
    assert "pgrep-self-match" in tags("cmd = \"pgrep -f 'make.py'\"\n", "builder.py")
    assert "colab-auth" in tags('subprocess.run(["colab", "sessions"])\n', "builder.py")
    assert "colab-auth" not in tags('subprocess.run(["colab", "--auth", "adc", "sessions"])\n', "builder.py")


def test_a_waiver_is_printed_and_does_not_fail():
    line = "pkill -f worker.sh  # ops-lint: ok this is run on the box by hand\n"
    found = lint_ops.lint_text("t.sh", line)
    assert found and all(f.waived == "this is run on the box by hand" for f in found)
    assert found[0].render().startswith("WAIVED t.sh:1:")


def test_every_finding_has_file_line_and_rule(tmp_path):
    f = tmp_path / "bad.sh"
    f.write_text("echo ok\npkill -f x\n", encoding="utf-8", newline="\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "lint_ops.py"), str(f)], capture_output=True, text=True)
    assert r.returncode == 1 and "bad.sh:2: [no-pkill-locally]" in r.stdout
    ok = tmp_path / "ok.sh"
    ok.write_text("echo ok\n", encoding="utf-8", newline="\n")
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "lint_ops.py"), str(ok)], capture_output=True, text=True).returncode == 0


def test_the_scripts_written_in_the_scene_work_are_clean():
    mine = ["worker_bringup.sh", "worker_run_job.sh", "start_workers.sh", "render_job.py", "scene_queue.py", "rate_pack.py", "lint_ops.py"]
    found = []
    for name in mine:
        p = ROOT / "scripts" / name
        if p.exists() and name != "lint_ops.py":
            found += [f.render() for f in lint_ops.lint_text(f"scripts/{name}", p.read_bytes().decode("utf-8"), True) if f.waived is None]
    assert found == [], "\n".join(found)
