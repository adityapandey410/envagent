"""Risk classification + typed HITL interrupt payloads."""

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
    automatable: NotRequired[bool]
    """Default True. False = not scriptable via CLI; 'command' is never executed."""
    manual_instructions: NotRequired[str | None]
    """Human instructions shown to the user when automatable is False."""


class Interrupt(TypedDict):
    type: Literal["confirm", "select", "checkbox"]
    message: str
    options: list[str] | None


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


_DIAGNOSTIC_PATTERNS = (
    "doctor",
    "diagnos",
    "check setup",
    "verify setup",
    "verify installation",
)


def is_diagnostic_step(step: PlanStep) -> bool:
    text = f"{step['command']} {step['description']}".lower()
    return any(pattern in text for pattern in _DIAGNOSTIC_PATTERNS)
