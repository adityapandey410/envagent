"""Risk classification + typed HITL interrupt payloads.

Produces *what* to ask, never *how* to ask it — cli.py is the only place
that knows about terminals/questionary. See CLAUDE.md's HITL design
section for the three interrupt kinds.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class PlanStep(TypedDict):
    description: str
    command: str
    risk: Literal["safe", "destructive"]
    undo_command: str | None
    check_command: NotRequired[str | None]
    """If present and it exits 0, the step's goal is already satisfied —
    skip the install/command entirely rather than re-running it."""


class Interrupt(TypedDict):
    type: Literal["confirm", "select", "checkbox"]
    message: str
    options: list[str] | None


# Deterministic safety net: never trust a plan-generating LLM's own risk
# self-report alone. If a command matches any of these, it is treated as
# destructive regardless of what the model claims — "HITL is a hard gate,
# not a suggestion" (CLAUDE.md). Err toward asking when uncertain.
_DESTRUCTIVE_PATTERNS = (
    "sudo",
    "rm -rf",
    "rm -r ",
    " rm ",
    "install",
    "uninstall",
    "curl ",
    "wget ",
    "| sh",
    "| bash",
    "chmod",
    "chown",
    "systemctl",
    "regedit",
    "diskutil",
    "format ",
)


def _is_destructive(step: PlanStep) -> bool:
    if step["risk"] == "destructive":
        return True
    command_lower = step["command"].lower()
    return any(pattern in command_lower for pattern in _DESTRUCTIVE_PATTERNS)


def classify_step(step: PlanStep) -> Interrupt | None:
    """Return a confirm interrupt for a destructive step, else None."""
    if not _is_destructive(step):
        return None
    return Interrupt(
        type="confirm",
        message=f"About to run:\n  {step['command']}\n{step['description']}\nProceed?",
        options=None,
    )
