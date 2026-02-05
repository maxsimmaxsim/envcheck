#!/usr/bin/env python3
# envcheck.py — minimal CLI object: env check + single run attempt
# Canon:
#   STDOUT: "SUCCESS" or "FAIL" (one line)
#   Exit:   0 or 1
#   Log:    ./envcheck.log (<=10 lines, facts only, no advice)

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


LOG_PATH = Path("./envcheck.log")
LOG_MAX_LINES = 10

# Entry point discovery priority (for directory input)
ENTRYPOINT_PATTERNS = [
    "main.py", "run.py", "app.py",
    "index.js", "main.js",
    "run.sh", "main.sh",
    "main.go",
]

# Single-run attempt timing
RUN_TIMEOUT_SECONDS = 3.0  # if still running at timeout => SUCCESS (it started)


@dataclass
class Target:
    kind: str  # "file" | "dir" | "command"
    path: Optional[Path] = None
    command: Optional[List[str]] = None
    entrypoint: Optional[Path] = None
    runtime: Optional[str] = None  # "python" | "node" | "bash" | "go" | "unknown"
    project_type: str = "unknown"  # "app" | "library" | "unknown"


class Log:
    def __init__(self) -> None:
        self.lines: List[str] = []

    def add(self, line: str) -> None:
        if len(self.lines) < LOG_MAX_LINES:
            self.lines.append(line.strip().replace("\n", " ")[:240])

    def write(self) -> None:
        try:
            LOG_PATH.write_text(
                "\n".join(self.lines) + ("\n" if self.lines else ""),
                encoding="utf-8",
            )
        except Exception:
            pass


def fail(log: Log) -> None:
    log.write()
    print("FAIL")
    raise SystemExit(1)


def success(log: Log) -> None:
    log.write()
    print("SUCCESS")
    raise SystemExit(0)


def unquote_if_wrapped(raw: str) -> tuple[str, bool]:
    s = raw.strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1], True
    return raw, False


def is_command_input(raw: str) -> bool:
    raw = raw.strip()

    unq, wrapped = unquote_if_wrapped(raw)
    if wrapped:
        try:
            if Path(unq).exists():
                return False
        except Exception:
            pass
        return True

    if any(ch.isspace() for ch in raw):
        try:
            if not Path(raw).exists():
                return True
        except Exception:
            return True

    return False


def guess_runtime_from_command(cmd: List[str]) -> str:
    head = Path(cmd[0]).name.lower()
    if head in ("python", "python3", "py"):
        return "python"
    if head == "node":
        return "node"
    if head in ("bash", "sh"):
        return "bash"
    if head == "go":
        return "go"
    return "unknown"


def find_entrypoint_in_dir(d: Path, log: Log) -> Optional[Path]:
    for name in ENTRYPOINT_PATTERNS:
        candidate = d / name
        if candidate.exists() and candidate.is_file():
            log.add(f"entrypoint: {candidate.name}")
            return candidate

    for ext in (".sh", ".js", ".go"):
        matches = sorted(d.glob(f"*{ext}"))
        if matches:
            log.add(f"entrypoint: {matches[0].name}")
            return matches[0]

    log.add("entrypoint: none")
    return None


def guess_runtime_from_file(f: Path, log: Log) -> str:
    ext = f.suffix.lower()
    if ext == ".py":
        return "python"
    if ext == ".js":
        return "node"
    if ext == ".sh":
        try:
            log.add(f"executable: {'yes' if os.access(f, os.X_OK) else 'no'}")
        except Exception:
            log.add("executable: unknown")
        return "bash"
    if ext == ".go":
        return "go"

    try:
        first = f.open("r", encoding="utf-8", errors="ignore").readline().strip()
    except Exception:
        first = ""
    if first.startswith("#!"):
        if "python" in first:
            return "python"
        if "node" in first:
            return "node"
        if "bash" in first or "/sh" in first:
            return "bash"

    log.add("runtime: unknown")
    return "unknown"


def _dir_has(d: Path, name: str) -> bool:
    try:
        p = d / name
        return p.exists() and p.is_file()
    except Exception:
        return False


def _dir_has_any_py(d: Path) -> bool:
    try:
        return any(d.glob("*.py"))
    except Exception:
        return False


def classify_project_dir(d: Path, entrypoint: Optional[Path], log: Log) -> tuple[str, str]:
    if entrypoint:
        rt = guess_runtime_from_file(entrypoint, log)
        return rt, "app"

    if _dir_has(d, "package.json"):
        return "node", "library"

    if _dir_has(d, "pyproject.toml") or _dir_has_any_py(d):
        if _dir_has_any_py(d):
            log.add("python_dir: py_files_present")
        return "python", "library"

    if _dir_has(d, "go.mod"):
        return "go", "library"

    return "unknown", "unknown"


def parse_target(raw: str, log: Log) -> Target:
    raw = raw.strip()

    unq, wrapped = unquote_if_wrapped(raw)
    if wrapped:
        try:
            if Path(unq).exists():
                raw = unq
        except Exception:
            pass

    if is_command_input(raw):
        try:
            cmd = shlex.split(raw)
        except ValueError:
            log.add("command: parse_error")
            return Target(kind="command", command=None, runtime="unknown")
        if not cmd:
            log.add("command: empty")
            return Target(kind="command", command=None, runtime="unknown")
        log.add(f"input: command={' '.join(cmd[:6])}{' ...' if len(cmd) > 6 else ''}")
        return Target(
            kind="command",
            command=cmd,
            runtime=guess_runtime_from_command(cmd),
            project_type="app",
        )

    p = Path(raw)
    if p.is_file():
        log.add(f"input: file={p}")
        rt = guess_runtime_from_file(p, log)
        return Target(kind="file", path=p, entrypoint=p, runtime=rt, project_type="app")

    if p.is_dir():
        log.add(f"input: dir={p}")
        ep = find_entrypoint_in_dir(p, log)
        rt, pt = classify_project_dir(p, ep, log)
        return Target(kind="dir", path=p, entrypoint=ep, runtime=rt, project_type=pt)

    log.add("input: not_found")
    return Target(kind="file", path=p, entrypoint=None, runtime="unknown")


def which_runtime(runtime: str) -> Optional[str]:
    if runtime == "python":
        return shutil.which("python3") or shutil.which("python")
    if runtime == "node":
        return shutil.which("node")
    if runtime == "bash":
        return shutil.which("bash") or shutil.which("sh")
    if runtime == "go":
        return shutil.which("go")
    return None


def get_runtime_version(exe: str, runtime: str, log: Log) -> None:
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        out = (proc.stdout or proc.stderr).strip()
        if out:
            log.add(f"runtime_version: {out.splitlines()[0][:120]}")
        else:
            log.add("runtime_version: unknown")
    except Exception:
        log.add("runtime_version: error")


def detect_project_facts(t: Target, log: Log) -> None:
    base: Optional[Path] = None
    if t.kind == "dir" and t.path:
        base = t.path
    elif t.entrypoint:
        base = t.entrypoint.parent
    if not base:
        return

    def present(p: Path) -> str:
        return "present" if p.exists() else "absent"

    if t.project_type != "unknown":
        log.add(f"project_type: {t.project_type}")

    pyproject = base / "pyproject.toml"
    requirements = base / "requirements.txt"

    venv_present = any(
        (base / name).exists() and (base / name).is_dir()
        for name in (".venv", "venv", "env")
    )

    package_json = base / "package.json"
    node_modules = base / "node_modules"
    package_lock = base / "package-lock.json"
    yarn_lock = base / "yarn.lock"
    pnpm_lock = base / "pnpm-lock.yaml"

    go_mod = base / "go.mod"

    rt = t.runtime or "unknown"
    if rt == "python":
        log.add(f"pyproject: {present(pyproject)}")
        log.add(f"requirements_txt: {present(requirements)}")
        log.add(f"venv: {'present' if venv_present else 'absent'}")
    elif rt == "node":
        log.add(f"package_json: {present(package_json)}")
        any_lock = package_lock.exists() or yarn_lock.exists() or pnpm_lock.exists()
        log.add(f"lockfile: {'present' if any_lock else 'absent'}")
        log.add(f"node_modules: {present(node_modules)}")
    elif rt == "go":
        log.add(f"go_mod: {present(go_mod)}")


def python_deps_probe_from_requirements(t: Target, log: Log, max_pkgs: int = 12) -> None:
    if t.runtime != "python":
        return

    base: Optional[Path] = None
    if t.kind == "dir" and t.path:
        base = t.path
    elif t.entrypoint:
        base = t.entrypoint.parent
    if not base:
        return

    req = base / "requirements.txt"
    if not req.exists() or not req.is_file():
        return

    try:
        lines = req.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        log.add("deps_probe: requirements_read_error")
        return

    pkgs: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith(("-", "--")) or "://" in s or s.startswith("git+"):
            continue
        name = s.split(";")[0].strip()
        name = name.split()[0].strip()
        if "[" in name:
            name = name.split("[", 1)[0]
        for op in ("==", ">=", "<=", "~=", ">", "<", "!="):
            if op in name:
                name = name.split(op, 1)[0].strip()
        if name:
            pkgs.append(name)
        if len(pkgs) >= max_pkgs:
            break

    if not pkgs:
        log.add("deps_probe: no_packages_parsed")
        return

    missing: List[str] = []
    checked = 0
    try:
        import importlib.util

        for p in pkgs:
            checked += 1
            mod_guess = p.replace("-", "_")
            if importlib.util.find_spec(mod_guess) is None:
                missing.append(p)
    except Exception:
        log.add("deps_probe: error")
        return

    log.add(f"deps_probe: checked={checked} missing={len(missing)}")
    if missing:
        head = ",".join(missing[:6])
        tail = " ..." if len(missing) > 6 else ""
        log.add(f"deps_missing: {head}{tail}")


def check_entrypoint_exists(t: Target, log: Log) -> bool:
    ep = t.entrypoint
    if not ep:
        log.add("entrypoint: missing")
        return False
    if not ep.exists():
        log.add("entrypoint: not_found")
        return False
    if not ep.is_file():
        log.add("entrypoint: not_file")
        return False
    return True


def build_run_command(t: Target, runtime_exe: Optional[str], log: Log) -> Optional[List[str]]:
    if t.kind == "command":
        if not t.command:
            log.add("run: command_missing")
            return None
        return t.command

    if not t.entrypoint:
        log.add("run: not_applicable")
        return None

    if not check_entrypoint_exists(t, log):
        return None

    ep = t.entrypoint
    assert ep is not None

    rt = t.runtime or "unknown"
    if rt in ("python", "node", "bash"):
        if not runtime_exe:
            log.add("runtime: missing")
            return None
        return [runtime_exe, str(ep)]
    if rt == "go":
        if not runtime_exe:
            log.add("runtime: missing")
            return None
        return [runtime_exe, "run", str(ep)]

    log.add("runtime: unknown")
    return None


def run_attempt(cmd: List[str], cwd: Optional[Path], log: Log) -> bool:
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log.add("run: not_found")
        return False
    except Exception:
        log.add("run: spawn_error")
        return False

    try:
        proc.wait(timeout=RUN_TIMEOUT_SECONDS)
        code = proc.returncode
        log.add(f"run: exit_code={code}")
        return code == 0
    except subprocess.TimeoutExpired:
        log.add("run: timeout_running")
        try:
            proc.terminate()
        except Exception:
            pass
        return True
    except Exception:
        log.add("run: wait_error")
        try:
            proc.terminate()
        except Exception:
            pass
        return False


def main() -> None:
    log = Log()

    if len(sys.argv) != 2:
        log.add("arg: missing_or_extra")
        fail(log)

    try:
        log.add(f"platform: {platform.system().lower()}_{platform.machine().lower()}")
    except Exception:
        pass

    t = parse_target(sys.argv[1], log)

    rt = t.runtime or "unknown"
    if rt == "unknown":
        log.add("runtime: unknown")
        fail(log)

    runtime_exe = which_runtime(rt)
    if not runtime_exe:
        log.add("runtime: missing")
        fail(log)

    get_runtime_version(runtime_exe, rt, log)

    detect_project_facts(t, log)
    python_deps_probe_from_requirements(t, log)

    if t.project_type == "library":
        success(log)

    if t.kind == "command":
        cmd = build_run_command(t, None, log)
        if not cmd:
            fail(log)
        ok = run_attempt(cmd, None, log)
        if ok:
            success(log)
        fail(log)

    cmd = build_run_command(t, runtime_exe, log)
    if not cmd:
        fail(log)

    cwd = t.path if (t.kind == "dir" and t.path) else None
    ok = run_attempt(cmd, cwd, log)
    if ok:
        success(log)
    fail(log)


if __name__ == "__main__":
    main()
