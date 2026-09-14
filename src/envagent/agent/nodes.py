"""plan / execute / verify / judge node implementations."""

from __future__ import annotations

import json
import time
from dataclasses import asdict

import json5
import json_repair
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from envagent.agent.prompts import JUDGE_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT
from envagent.agent.state import Assessment, AgentState
from envagent.config.credentials import get_api_key
from envagent.config.settings import load_settings
from envagent.docs.fetcher import extract_os_section, fetch_doc
from envagent.hitl.gate import classify_step, is_diagnostic_step
from envagent.providers.base import Provider
from envagent.providers.registry import get_provider
from envagent.recipes.registry import match_recipe
from envagent.system.executor import ExecutionResult
from envagent.system.executor import run as run_command
from envagent.system.executor import run_check
from envagent.system.os_detect import detect_system
from envagent.system.permissions import can_elevate


class NotConfiguredError(RuntimeError):
    pass


class NoStepsPlannedError(RuntimeError):
    pass


def _active_provider_and_key() -> tuple[Provider, str]:
    settings = load_settings()
    if not settings.provider:
        raise NotConfiguredError("No provider configured. Run `envagent init` first.")
    api_key = get_api_key(settings.provider)
    if not api_key:
        raise NotConfiguredError(
            f"No stored API key for {settings.provider!r}. Run `envagent init` first."
        )
    return get_provider(settings.provider), api_key


_MAX_GROUNDING_CHARS = 6000  # ~1500 tokens — bounds cost same as the judge's per-step cap


def _parse_json_lenient(raw: str):
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json5.loads(text)
    except ValueError:
        pass
    return json_repair.loads(text)


def _parse_plan(raw: str) -> list[dict]:
    return _parse_json_lenient(raw)


def plan_node(state: AgentState) -> AgentState:
    writer = get_stream_writer()
    provider, api_key = _active_provider_and_key()
    system_info = detect_system()
    writer({"type": "system_info", "description": system_info.describe()})

    elevation_ok = can_elevate()
    if not elevation_ok:
        writer({"type": "cannot_elevate"})

    grounding = ""
    ide_choice = state.get("ide_choice")
    recipe = match_recipe(state["goal"])
    if recipe is not None:
        writer({"type": "recipe_matched", "name": recipe.name})
        if recipe.ide_choice is not None and ide_choice is None:
            ide_choice = interrupt(
                {
                    "type": "select",
                    "message": recipe.ide_choice.message,
                    "options": recipe.ide_choice.options,
                }
            )
        doc_content = fetch_doc(recipe.doc_url)
        os_section = extract_os_section(doc_content, system_info.os_key)[:_MAX_GROUNDING_CHARS]
        grounding = (
            f"\n\nOfficial documentation excerpt for {recipe.name} "
            f"({system_info.os_key}):\n{os_section}"
        )
        if ide_choice:
            grounding += f"\n\nThe user chose {ide_choice} as their IDE."

    elevation_note = (
        ""
        if elevation_ok
        else "\n\nNote: this user cannot run privileged (sudo/admin) commands on this "
        "machine. Avoid steps that require elevation where a non-privileged "
        "alternative exists; where elevation is unavoidable, still include the step "
        "(it will be flagged to the user) rather than silently dropping it."
    )
    user_prompt = (
        f"Operating system: {system_info.describe()}\n\n"
        f"Goal: {state['goal']}{grounding}{elevation_note}"
    )
    raw = provider.complete(api_key, PLAN_SYSTEM_PROMPT, user_prompt)
    plan = _parse_plan(raw)
    if not plan:
        raise NoStepsPlannedError(
            "No setup steps were generated for that request — it may not "
            "be a developer environment setup task, or nothing needs to "
            "change. Try something like 'set up flutter for android "
            "development'."
        )
    writer({"type": "plan_ready", "plan": plan})
    return {
        **state,
        "plan": plan,
        "current_step_index": 0,
        "results": [],
        "status": "executing",
        **({"ide_choice": ide_choice} if ide_choice else {}),
    }


def execute_node(state: AgentState) -> AgentState:
    step = state["plan"][state["current_step_index"]]
    writer = get_stream_writer()

    def on_line(line: str) -> None:
        writer({"type": "output_line", "line": line})

    check_command = step.get("check_command")
    if check_command and is_diagnostic_step(step):
        check_command = None
    check_result = None
    if check_command:
        writer(
            {
                "type": "check_start",
                "description": step["description"],
                "command": check_command,
            }
        )
        check_result = run_check(check_command, on_line=on_line)
        if check_result.succeeded:
            writer({"type": "check_satisfied", "description": step["description"]})
            entry = asdict(check_result)
            entry["skipped_install"] = True
            return {**state, "results": [*state["results"], entry]}

    if not step.get("automatable", True):
        instructions = step.get("manual_instructions") or step["description"]
        writer(
            {
                "type": "manual_action_needed",
                "description": step["description"],
                "instructions": instructions,
            }
        )
        confirmed = interrupt(
            {
                "type": "confirm",
                "message": (
                    f"This can't be automated: {step['description']}\n{instructions}\n\n"
                    "Have you completed this yourself? (No stops the run here — "
                    "later steps may depend on it.)"
                ),
                "options": None,
            }
        )
        if not confirmed:
            return {**state, "status": "failed"}

        if check_command:
            writer(
                {
                    "type": "check_start",
                    "description": step["description"],
                    "command": check_command,
                }
            )
            recheck = run_check(check_command, on_line=on_line)
            if recheck.succeeded:
                writer({"type": "check_satisfied", "description": step["description"]})
                entry = asdict(recheck)
                entry["skipped_install"] = True
                return {**state, "results": [*state["results"], entry]}
            writer(
                {
                    "type": "manual_action_still_not_detected",
                    "description": step["description"],
                }
            )
            return {**state, "status": "failed"}

        now = time.time()
        entry = asdict(
            ExecutionResult(
                command=step.get("command", ""),
                returncode=0,
                stdout="",
                stderr="",
                undo_command=None,
                started_at=now,
                finished_at=now,
                kind="manual",
            )
        )
        entry["needs_manual_action"] = True
        entry["manual_instructions"] = instructions
        return {**state, "results": [*state["results"], entry]}

    interrupt_payload = classify_step(step)
    if interrupt_payload is not None:
        approved = interrupt(interrupt_payload)
        if not approved:
            return {**state, "status": "failed"}

    writer(
        {
            "type": "command_start",
            "description": step["description"],
            "command": step["command"],
        }
    )
    result = run_command(step, on_line=on_line)
    results = [*state["results"], asdict(result)]
    return {**state, "results": results}


def verify_node(state: AgentState) -> AgentState:
    if state["status"] == "failed":
        return state

    last_result = state["results"][-1]
    if last_result["returncode"] != 0:
        return {**state, "status": "failed"}

    next_index = state["current_step_index"] + 1
    if next_index >= len(state["plan"]):
        return {**state, "status": "done", "current_step_index": next_index}
    return {**state, "current_step_index": next_index, "status": "executing"}


_MAX_JUDGE_OUTPUT_CHARS = 1500


def _truncate(text: str, limit: int = _MAX_JUDGE_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated, {len(text) - limit} more characters]"


def _build_judge_transcript(state: AgentState) -> str:
    lines = [f"Goal: {state['goal']}", ""]
    for step, result in zip(state["plan"], state["results"], strict=True):
        lines.append(f"Step: {step['description']}")
        if result.get("needs_manual_action"):
            lines.append(
                "NOT AUTOMATED — this cannot be done via CLI and still needs "
                f"manual action by the user: {result.get('manual_instructions', '')}"
            )
            lines.append("")
            continue
        lines.append(f"Command: {result['command']}")
        lines.append(f"Exit code: {result['returncode']}")
        if result.get("skipped_install"):
            lines.append("(skipped — an idempotency check found this already satisfied)")
        output = result.get("stdout", "")
        if output.strip():
            lines.append(f"Output:\n{_truncate(output)}")
        lines.append("")
    return "\n".join(lines)


def judge_node(state: AgentState) -> AgentState:
    """Reviews the completed run against the goal via one LLM call."""
    writer = get_stream_writer()
    writer({"type": "judging_start"})
    provider, api_key = _active_provider_and_key()
    transcript = _build_judge_transcript(state)
    raw = provider.complete(api_key, JUDGE_SYSTEM_PROMPT, transcript)
    try:
        parsed = _parse_json_lenient(raw)
        assessment: Assessment = {
            "achieved": bool(parsed["achieved"]),
            "summary": str(parsed["summary"]),
        }
    except Exception:
        assessment = {
            "achieved": False,
            "summary": "Could not parse the verification response — please review the output above manually.",
        }
    writer({"type": "judgement_ready", "assessment": assessment})
    return {**state, "assessment": assessment}
