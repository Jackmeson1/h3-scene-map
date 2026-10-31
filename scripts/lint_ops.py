#!/usr/bin/env python3
"""Static checker for the operations scripts: the shell files, and the shell text that Python files send to the box.

Every rule below comes from a real incident. A finding prints as  file:line: [rule] message  and the offending line, and the exit status is 1.
A line can be waived with an inline comment  # ops-lint: ok <reason>  ; the waiver is printed (WAIVED ...) so it stays visible, and does not fail the run.

    lint_ops.py                    scan scripts/*.sh, scripts/*.ps1 and scripts/*.py of this project
    lint_ops.py FILE [FILE ...]    scan these files

What static analysis cannot do (stated, not hidden):
  - It reads lines. Quoting and multi-line strings are approximated; a pattern held in a variable (pgrep -f "$x") cannot be judged.
  - It cannot know what the runtime does to a killed child. Rule `exit-status` only flags the shapes that make a killed or failed child look
    like success (exit code read after a pipeline, `|| true` on the job, a trap that exits 0). Whether Git Bash, Colab or Windows really
    report a kill as non-zero is a runtime fact that only a real run shows.
  - It cannot know whether a given remote command is correct, only that it has a shape that has failed before.
"""
import re
import sys
from pathlib import Path

WAIVER = re.compile(r"#\s*ops-lint:\s*ok\b\s*(.*)$")
BRACKET = re.compile(r"\[[A-Za-z0-9_]\]")


class Finding:
    def __init__(self, path, line_no, rule, message, text, waived=None):
        self.path, self.line_no, self.rule, self.message, self.text, self.waived = path, line_no, rule, message, text.strip(), waived

    def render(self):
        head = "WAIVED " if self.waived is not None else ""
        why = f" (waiver: {self.waived or 'no reason given'})" if self.waived is not None else ""
        return f"{head}{self.path}:{self.line_no}: [{self.rule}] {self.message}{why}\n    {self.text[:200]}"


def is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def code_part(line: str) -> str:
    """The line without a trailing ' # comment' (rough: a # preceded by space and not inside quotes is not tracked)."""
    m = re.search(r"\s#\s", line)
    return line[: m.start()] if m else line


# ---- rules. Each takes (ctx, line_no, line) and returns a list of (rule, message) -------------------------------------------------------

def rule_pgrep_self_match(ctx, n, line):
    out = []
    code = code_part(line)
    for m in re.finditer(r"\b(pgrep|pkill)\s+((?:-[A-Za-z]+\s+)*)(['\"]?)([^'\"\s|;&)]+)\3", code):
        flags, pattern = m.group(2), m.group(4)
        if "f" not in flags.replace("-", "") and not re.search(r"-\w*f", flags):
            continue  # without -f only the process name is matched, which cannot be the shell command line
        if pattern.startswith("$"):
            continue  # a variable: cannot be judged
        if not BRACKET.search(pattern):
            out.append(("pgrep-self-match", f"`{m.group(1)} -f {pattern}` can match its own command line (and the shell that runs it); write the pattern as `[{pattern[0]}]{pattern[1:]}`"))
    if re.search(r"\bps\b[^|]*\|\s*grep\s+(?!-v)[^|]*", code) and not re.search(r"grep\s+-v\s+grep", code) and "grep" in code:
        m = re.search(r"\|\s*grep\s+(?:-\w+\s+)*(['\"]?)([^'\"\s|]+)\1", code)
        if m and not BRACKET.search(m.group(2)) and not m.group(2).startswith("$"):
            out.append(("pgrep-self-match", f"`ps | grep {m.group(2)}` matches the grep itself; use the `[x]yz` bracket form"))
    if ctx.suffix == ".ps1" or "powershell" in code.lower() or "Stop-Process" in code:
        if re.search(r"Stop-Process|taskkill|\.Kill\(\)", code) and re.search(r"-(match|like)\s+['\"]([^'\"]+)['\"]", code):
            pat = re.search(r"-(match|like)\s+['\"]([^'\"]+)['\"]", code).group(2)
            if not BRACKET.search(pat):
                out.append(("pgrep-self-match", f"PowerShell `-match '{pat}'` used to stop processes can match the PowerShell command line that contains it; use a bracket form such as `[{pat[0]}]{pat[1:]}`"))
    return out


def rule_background_and_list(ctx, n, line):
    code = code_part(line)
    if is_comment(line):
        return []
    out = []
    bg = re.search(r"(?<![&>])&\s*[\"')]*\s*$", code) and not re.search(r"&&\s*$", code)
    if bg and ("setsid" in code or "nohup" in code):
        if "&&" in code[: code.rfind("&")]:
            out.append(("background-and-list", "a backgrounded `a && b && c &` sent to the box leaves a subshell holding the kernel's stdout pipe, so the Jupyter kernel blocks until c ends; write `a; b; setsid cmd > log 2>&1 < /dev/null &`"))
        if "/dev/null" not in code or not re.search(r">\s*\S+\s+2>&1", code):
            out.append(("background-redirects", "a background job on the box must redirect output and input: `setsid cmd > log 2>&1 < /dev/null &`, or it keeps the kernel's pipes open"))
    return out


def rule_tail_success(ctx, n, line):
    code = code_part(line)
    if "colab" in code and re.search(r"\|\s*tail\s+(-n\s*1|-1)\s*\|\s*grep\b", code):
        return [("tail-n1-success", "success decided from the last line of colab output: the update notice can land last. Capture all output and search it (`said=$(...); case \"$said\" in *Uploaded*)`)")]
    if "colab" in code and re.search(r"\$\([^)]*\|\s*tail\s+(-n\s*1|-1)\s*\)", code) and re.search(r"\[\s|\bcase\b|\bif\b|&&|\|\|", code):
        return [("tail-n1-success", "a decision made on the last line of colab output: the update notice can land last")]
    return []


def rule_windows_python_cr(ctx, n, line):
    """Multi-line output of a Windows Python call keeps CRLF on every line. A single value assigned or quoted is safe here: measured, Git Bash
    drops the final CRLF. So only loops and `while read` pipelines are flagged."""
    if is_comment(line):
        return []
    code = code_part(line)
    msg = "output of a Windows Python call used in a loop keeps CRLF on every line; pipe it through `tr -d '\\015'`"
    strips = re.compile(r"tr\s+-d\s+'\\015'")
    m = re.search(r"\bfor\s+\w+\s+in\s+\$\(\s*((?:\$Q|python)\b[^)]*)\)", code)
    if m and not strips.search(m.group(1)):
        return [("windows-python-cr", msg)]
    m = re.search(r"(?<![\w/-])(python|\$Q)\b[^|;]*\|\s*(?!tr\s+-d\s+'\\015')while\s+(IFS=\S*\s+)?read\b", code)
    if m:
        return [("windows-python-cr", "output of a Windows Python call read line by line keeps CRLF; pipe it through `tr -d '\\015'` first")]
    return []


def rule_cr_handling(ctx, n, line):
    out = []
    if "\r" in line.rstrip("\n"):
        out.append(("literal-cr", "a literal carriage return in a shell file (CRLF line endings) breaks bash; convert the file to LF"))
    if is_comment(line):
        return out
    code = code_part(line)
    for m in re.finditer(r"\btr\s+(-[a-z]*d[a-z]*)\s+('[^']*'|\"[^\"]*\"|\S*)", code):
        arg = m.group(2)
        inner = arg.strip("'\"")
        if inner == "" or inner == "\r":
            out.append(("tr-d-empty", "`tr -d` with an empty argument deletes nothing and errors; use `tr -d '\\015'`"))
        elif re.fullmatch(r"(r|\\r|\\\\r)\s*", inner):
            out.append(("tr-d-bare-cr", f"`tr -d {arg}` is not a reliable carriage-return delete (a shell or tool may eat the backslash and delete the letter r); require `tr -d '\\015'`"))
    return out


def rule_msys_paths(ctx, n, line):
    if not ctx.exports_nopathconv or is_comment(line):
        return []
    code = code_part(line)
    out = []
    if re.search(r"(?<![\w/-])python(\.exe)?\s+(-\w+\s+)*[\"']?(\$root|\$\{root\}|\$HOME|~|/c/|/[a-z]/|\$\(pwd\))", code) and "cygpath" not in code:
        out.append(("msys-path", "a POSIX path handed to Windows Python while MSYS_NO_PATHCONV is exported is not converted; wrap it with `$(cygpath -w ...)`"))
    if re.search(r"(?<![\w-])colab\b.*\b(upload|download)\b", code) and re.search(r"\"\$(root|\{root\}|tmp|f|1)\b[^\"]*\"", code) and "cygpath" not in code:
        out.append(("msys-path", "a local path given to the Windows colab client while MSYS_NO_PATHCONV is exported must go through `cygpath -w`"))
    return out


def rule_colab_auth(ctx, n, line):
    if is_comment(line) or re.match(r"\s*(echo|printf)\b", line):
        return []
    code = code_part(line)
    out = []
    for m in re.finditer(r"(?:^|[\s(|;&`\"'])colab\s+(?!--auth\s+adc\b)(--?\w[\w-]*\s+)?(new|exec|upload|download|sessions|usage|stop|list|ls|mount|dfs)\b", code):
        out.append(("colab-auth", "`colab` without `--auth adc` falls back to an interactive OAuth prompt and hangs"))
        break
    if ctx.suffix == ".py" and re.search(r"\[\s*['\"]colab['\"]\s*,(?!\s*['\"]--auth['\"]\s*,\s*['\"]adc['\"])", code):
        out.append(("colab-auth", "`colab` called from Python without --auth adc"))
    return out


def rule_no_timeout(ctx, n, line):
    if not ctx.is_worker or is_comment(line) or re.match(r"\s*(echo|printf)\b", line):
        return []
    code = code_part(line)
    out = []
    for tool in ("colab", "curl"):
        for m in re.finditer(rf"(?:^|[\s(|;&`\"'{{]){tool}\s+(--auth|-\w|new|exec|upload|download|sessions|usage|stop|https?://)", code):
            head = code[: m.start()]
            if re.search(r"timeout\s+(-\w+\s+)*[\"$\w{}:-]+\s*$", head) or "--max-time" in code or "-m " in code and tool == "curl":
                continue
            if re.search(r"\b(timeout)\s+[^|;&]*$", head):
                continue
            out.append(("no-timeout", f"`{tool}` in a long-running worker without a hard `timeout`: it can hang the whole worker"))
            break
    if re.search(r"(?:^|[\s(|;&`\"'])(rx|scripts/rx\.sh|\"?\$root/scripts/rx\.sh\"?)\s", code) and not ctx.rx_has_timeout:
        out.append(("no-timeout", "`rx` calls colab exec, and rx.sh has no hard `timeout` of its own"))
    return out


def rule_rm_glob(ctx, n, line):
    if is_comment(line):
        return []
    code = code_part(line)
    for m in re.finditer(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f?|-[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*)\s+([^|;&]*)", code):
        args = m.group(2)
        if re.search(r"[*?]|\[\w", re.sub(r"\\\*", "", args)) and not re.search(r"^\s*['\"]?[^*?]*\.(tmp|part)\b", args):
            return [("rm-rf-glob", "`rm -rf` on a glob deletes whatever the glob matches today, including things you did not mean to; name the directory")]
    return []


def rule_pkill_local(ctx, n, line):
    code = code_part(line)
    if is_comment(line) or ctx.suffix != ".sh":
        return []
    if re.search(r"(?:^|[\s(;&|`])(pkill|killall|pgrep)\s", code) and not re.search(r"\brx\b|\"[^\"]*(pkill|killall|pgrep)|'[^']*(pkill|killall|pgrep)", code):
        return [("no-pkill-locally", "pkill, killall and pgrep do not exist in Git Bash; on the box run them through rx, locally use `ps -W` / `taskkill`")]
    return []


def rule_timeout_function(ctx, n, line):
    if is_comment(line):
        return []
    m = re.search(r"\btimeout\s+(?:-\w+\s+)*[\"$\w{}]+\s+(\w+)\b", code_part(line))
    if m and m.group(1) in ctx.functions:
        return [("timeout-function", f"`timeout` cannot run the shell function `{m.group(1)}` (it execs a program); call a script, or put the timeout inside the function")]
    return []


def rule_exit_status(ctx, n, line):
    out = []
    code = code_part(line)
    if is_comment(line):
        return out
    if re.search(r"\|\|\s*(true|:)\s*(;|$)", code) and re.search(r"render_job|runner|worker_run|job", code):
        out.append(("exit-status", "`|| true` after a job command turns a failure or a kill into success"))
    if re.match(r"\s*trap\s+['\"][^'\"]*\bexit\s+0\b", code):
        out.append(("exit-status", "a trap that exits 0 reports a killed process as success"))
    if n > 1 and "$?" in code and not ctx.pipefail:
        prev = ctx.lines[n - 2]
        if re.search(r"[^|]\|[^|]", code_part(prev)) and not prev.rstrip().endswith("\\") and "PIPESTATUS" not in code:
            out.append(("exit-status", "`$?` after a pipeline is the status of its last command (usually tail or grep), not of the job; use `set -o pipefail` or ${PIPESTATUS[0]}"))
    return out


RULES = [rule_pgrep_self_match, rule_background_and_list, rule_tail_success, rule_windows_python_cr, rule_cr_handling, rule_msys_paths,
         rule_colab_auth, rule_no_timeout, rule_rm_glob, rule_pkill_local, rule_timeout_function, rule_exit_status]
PY_RULES = {rule_pgrep_self_match, rule_background_and_list, rule_tail_success, rule_colab_auth, rule_rm_glob}  # Python files send shell text to the box


class Ctx:
    def __init__(self, path: Path, text: str, rx_has_timeout: bool):
        self.path, self.suffix = path, path.suffix
        self.lines = text.split("\n")
        self.exports_nopathconv = bool(re.search(r"^\s*export\s+MSYS_NO_PATHCONV", text, re.M))
        self.functions = set(re.findall(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{", text, re.M)) | set(re.findall(r"[;{]\s*(\w+)\(\)\s*\{", text))
        self.pipefail = "pipefail" in text
        self.is_worker = bool(re.search(r"^\s*(while|until)\b|\bfor\b[^\n]*\bin\b\s+\$\(seq", text, re.M)) or path.name.startswith(("worker", "budget", "preempt", "sync", "restore", "start_workers"))
        self.rx_has_timeout = rx_has_timeout


def lint_text(name: str, text: str, rx_has_timeout: bool = True) -> list:
    path = Path(name)
    ctx = Ctx(path, text, rx_has_timeout)
    rules = [r for r in RULES if path.suffix != ".py" or r in PY_RULES]
    findings = []
    seen_cr = False
    for n, line in enumerate(ctx.lines, start=1):
        waiver = WAIVER.search(line)
        for rule in rules:
            for tag, message in rule(ctx, n, line.rstrip("\n")):
                if tag == "literal-cr":
                    if seen_cr:
                        continue
                    seen_cr = True
                    message += " (" + str(sum(1 for l in ctx.lines if chr(13) in l)) + " lines)"
                findings.append(Finding(name, n, tag, message, line.rstrip("\r\n"), waiver.group(1).strip() if waiver else None))
    return findings


def default_targets(root: Path) -> list:
    scripts = root / "scripts"
    return sorted(p for pattern in ("*.sh", "*.ps1", "*.py") for p in scripts.glob(pattern) if p.name != "lint_ops.py")


def run(paths: list, root: Path) -> tuple:
    rx = root / "scripts" / "rx.sh"
    rx_has_timeout = rx.exists() and bool(re.search(r"\btimeout\b[^\n]*\bcolab\b", rx.read_text(encoding="utf-8", errors="replace")))
    findings = []
    for p in paths:
        text = Path(p).read_bytes().decode("utf-8", errors="replace")  # keep any CR byte: it is a finding
        findings += lint_text(str(Path(p).relative_to(root)) if Path(p).is_absolute() and root in Path(p).parents else str(p), text, rx_has_timeout)
    return [f for f in findings if f.waived is None], [f for f in findings if f.waived is not None]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(__file__).resolve().parent.parent
    paths = [Path(a).resolve() for a in argv] if argv else default_targets(root)
    bad, waived = run(paths, root)
    for f in waived:
        print(f.render())
    for f in bad:
        print(f.render())
    print(f"lint_ops: {len(paths)} files, {len(bad)} finding(s), {len(waived)} waived")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
