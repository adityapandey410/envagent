"""Subprocess execution wrapped with logging + an undo-log entry per step.

All command logging happens here, not scattered at call sites, so every
executed command is auditable in one place regardless of which graph node
triggered it. Each log line also carries the step's undo command (if the
plan declared one) — the basis for a future `envagent undo` (Phase 5).
"""

from __future__ import annotations

import json
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
    """'execute' (the step's real command ran) or 'check' (an idempotency
    pre-check ran instead)."""

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _run_command(
    command: str, on_line: Callable[[str], None] | None = None
) -> tuple[int, str, str, float, float]:
    """Runs a command and streams its output line-by-line to on_line as it
    happens (real-time visibility), while still returning the full
    captured output for logging. stdout/stderr are merged — a long-running
    command (an install, a download) is otherwise indistinguishable from a
    hang with no live output at all."""
    started_at = time.time()
    proc = subprocess.Popen(
        command,
        shell=True,
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
    """Run a step's idempotency check_command. Logged like any other
    executed command, tagged kind='check' for auditability."""
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
