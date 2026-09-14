"""Graph state schema."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from envagent.hitl.gate import PlanStep


class Assessment(TypedDict):
    achieved: bool
    summary: str


class AgentState(TypedDict):
    goal: str
    """The user's natural-language request, e.g. 'set up Flutter for Android'."""

    status: str
    """'planning' | 'executing' | 'done' | 'failed'."""

    plan: list[PlanStep]
    current_step_index: int
    results: list[dict]
    """Serialized ExecutionResult per completed step, in order."""

    assessment: NotRequired[Assessment]
    """Set by judge_node only on the 'done' path — an honest, LLM-reviewed
    verdict on whether the goal was actually achieved (not just whether
    every command exited 0). Absent on a 'failed' run: that path is
    already an honest signal on its own."""

    ide_choice: NotRequired[str]
    """Set by plan_node when a matched recipe declares an ide_choice and
    the user has answered its select interrupt. Persisted so a resumed
    run doesn't ask again."""
