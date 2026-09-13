"""Graph state schema."""

from __future__ import annotations

from typing import TypedDict

from envagent.hitl.gate import PlanStep


class AgentState(TypedDict):
    goal: str
    """The user's natural-language request, e.g. 'set up Flutter for Android'."""

    status: str
    """'planning' | 'executing' | 'done' | 'failed'."""

    plan: list[PlanStep]
    current_step_index: int
    results: list[dict]
    """Serialized ExecutionResult per completed step, in order."""
