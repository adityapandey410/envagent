"""plan / execute / verify node implementations.

Phase 1 scope: plan_node asks the configured LLM directly from the goal —
no recipe lookup, no doc-grounding yet (that's Phase 2). This proves the
loop/interrupt/logging mechanics; plan *quality* improves once recipes and
doc-fetching land.
"""

from __future__ import annotations

import json
import platform
from dataclasses import asdict

from langgraph.types import interrupt

from envagent.agent.prompts import PLAN_SYSTEM_PROMPT
from envagent.agent.state import AgentState
from envagent.config.credentials import get_api_key
from envagent.config.settings import load_settings
from envagent.hitl.gate import classify_step
from envagent.providers.base import Provider
from envagent.providers.registry import get_provider
from envagent.system.executor import run as run_command
from envagent.system.executor import run_check


class NotConfiguredError(RuntimeError):
    pass


def _active_provider_and_key() -> tuple[Provider, str]:
    settings = load_settings()
    if not settings.provider:
        raise NotConfiguredError("No provider configured. Run `envagent` to set one up first.")
    api_key = get_api_key(settings.provider)
    if not api_key:
        raise NotConfiguredError(
            f"No stored API key for {settings.provider!r}. Run `envagent` to set one up first."
        )
    return get_provider(settings.provider), api_key


_OS_NAMES = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}


def _describe_os() -> str:
    system = platform.system()
    name = _OS_NAMES.get(system, system)
    return f"{name} ({platform.machine()}, release {platform.release()})"


def _parse_plan(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text)


def plan_node(state: AgentState) -> AgentState:
    provider, api_key = _active_provider_and_key()
    user_prompt = f"Operating system: {_describe_os()}\n\nGoal: {state['goal']}"
    raw = provider.complete(api_key, PLAN_SYSTEM_PROMPT, user_prompt)
    plan = _parse_plan(raw)
    return {
        **state,
        "plan": plan,
        "current_step_index": 0,
        "results": [],
        "status": "executing",
    }


def execute_node(state: AgentState) -> AgentState:
    step = state["plan"][state["current_step_index"]]

    check_command = step.get("check_command")
    if check_command:
        check_result = run_check(check_command)
        if check_result.succeeded:
            # Already satisfied — skip the install entirely. No HITL
            # interrupt either: nothing destructive is about to happen.
            entry = asdict(check_result)
            entry["skipped_install"] = True
            return {**state, "results": [*state["results"], entry]}

    interrupt_payload = classify_step(step)
    if interrupt_payload is not None:
        approved = interrupt(interrupt_payload)
        if not approved:
            return {**state, "status": "failed"}

    result = run_command(step)
    results = [*state["results"], asdict(result)]
    return {**state, "results": results}


def verify_node(state: AgentState) -> AgentState:
    if state["status"] == "failed":
        # execute_node already marked this failed (e.g. a HITL rejection)
        # without producing a result to check.
        return state

    last_result = state["results"][-1]
    if last_result["returncode"] != 0:
        return {**state, "status": "failed"}

    next_index = state["current_step_index"] + 1
    if next_index >= len(state["plan"]):
        return {**state, "status": "done", "current_step_index": next_index}
    return {**state, "current_step_index": next_index, "status": "executing"}
