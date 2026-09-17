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
    """Set by judge_node; absent on a 'failed' run."""

    ide_choice: NotRequired[str]
    """Set by plan_node once the recipe's select interrupt is answered."""

    clarification: NotRequired[str]
    """Set by clarify_node once a freeform goal's ambiguity is resolved."""
