"""Subprocess execution wrapped with logging + an undo-log entry per step."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_log_dir

from envagent.hitl.gate import PlanStep

APP_NAME = "envagent"


def log_file() -> Path:
    log_dir = Path(user_log_dir(APP_NAME))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "run_log.jsonl"


@dataclass
class ExecutionResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    undo_command: str | None
    started_at: float
    finished_at: float
    kind: str = "execute"
    """'execute' or 'check'."""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _popen_args(command: str) -> list[str] | str:
    """On Windows, run via PowerShell explicitly rather than letting `shell=True`
    fall through to cmd.exe, which understands neither bash nor PowerShell syntax."""
    if platform.system() == "Windows":
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    return command


def _read_registry_path(hive: int, subkey: str) -> str:
    import winreg

    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return value
    except OSError:
        return ""


def _windows_env_with_fresh_path() -> dict[str, str]:
    """A persistent PATH change (setx / [Environment]::SetEnvironmentVariable)
    writes to the registry, but this already-running process's own
    os.environ snapshot (taken once at startup) never picks it up — so an
    earlier step's PATH change wouldn't be visible to a later step's
    subprocess, even though both ran on Windows via _popen_args. Re-read
    User+Machine PATH from the registry before every Windows command
    instead of trusting the inherited environment."""
    env = os.environ.copy()
    try:
        import winreg

        machine_path = _read_registry_path(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        )
        user_path = _read_registry_path(winreg.HKEY_CURRENT_USER, "Environment")
        combined = ";".join(p for p in (machine_path, user_path) if p)
        if combined:
            env["PATH"] = os.path.expandvars(combined)
    except Exception:
        pass  # fall back to the inherited environment rather than crash a run
    return env


def _run_command(
    command: str, on_line: Callable[[str], None] | None = None
) -> tuple[int, str, str, float, float]:
    """Streams output line-by-line via on_line while capturing it in full; stdout/stderr merged."""
    started_at = time.time()
    args = _popen_args(command)
    env = _windows_env_with_fresh_path() if platform.system() == "Windows" else None
    proc = subprocess.Popen(
        args,
        shell=isinstance(args, str),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        if on_line is not None:
            on_line(line.rstrip("\n"))
    proc.wait()
    return proc.returncode, "".join(lines), "", started_at, time.time()


def run(step: PlanStep, on_line: Callable[[str], None] | None = None) -> ExecutionResult:
    returncode, stdout, stderr, started_at, finished_at = _run_command(
        step["command"], on_line
    )
    result = ExecutionResult(
        command=step["command"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        undo_command=step.get("undo_command"),
        started_at=started_at,
        finished_at=finished_at,
        kind="execute",
    )
    _append_log(result)
    return result


def run_check(command: str, on_line: Callable[[str], None] | None = None) -> ExecutionResult:
    """Run a step's check_command, logged with kind='check'."""
    returncode, stdout, stderr, started_at, finished_at = _run_command(command, on_line)
    result = ExecutionResult(
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        undo_command=None,
        started_at=started_at,
        finished_at=finished_at,
        kind="check",
    )
    _append_log(result)
    return result


def _append_log(result: ExecutionResult) -> None:
    with log_file().open("a") as f:
        f.write(json.dumps(asdict(result)) + "\n")
