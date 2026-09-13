"""plan / execute / verify node implementations.

Phase 1 scope: plan_node asks the configured LLM directly from the goal —
no recipe lookup, no doc-grounding yet (that's Phase 2). This proves the
loop/interrupt/logging mechanics; plan *quality* improves once recipes and
doc-fetching land.
"""

from __future__ import annotations

import json
import platform
import time
from dataclasses import asdict

import json5
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from envagent.agent.prompts import JUDGE_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT
from envagent.agent.state import Assessment, AgentState
from envagent.config.credentials import get_api_key
from envagent.config.settings import load_settings
from envagent.hitl.gate import classify_step
from envagent.providers.base import Provider
from envagent.providers.registry import get_provider
from envagent.system.executor import ExecutionResult
from envagent.system.executor import run as run_command
from envagent.system.executor import run_check


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


_OS_NAMES = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}


def _describe_os() -> str:
    system = platform.system()
    name = _OS_NAMES.get(system, system)
    return f"{name} ({platform.machine()}, release {platform.release()})"


def _parse_json_lenient(raw: str):
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Models occasionally fall back to single-quoted strings when a
        # command needs literal double quotes inside it (e.g. `bash -c
        # "..."`) instead of escaping them — invalid strict JSON, but
        # unambiguous intent. json5 accepts it; strict json.loads stays
        # the first attempt since it's stricter and faster.
        return json5.loads(text)


def _parse_plan(raw: str) -> list[dict]:
    return _parse_json_lenient(raw)


def plan_node(state: AgentState) -> AgentState:
    writer = get_stream_writer()
    provider, api_key = _active_provider_and_key()
    os_description = _describe_os()
    writer({"type": "system_info", "description": os_description})

    user_prompt = f"Operating system: {os_description}\n\nGoal: {state['goal']}"
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
    }


def execute_node(state: AgentState) -> AgentState:
    step = state["plan"][state["current_step_index"]]
    writer = get_stream_writer()

    def on_line(line: str) -> None:
        writer({"type": "output_line", "line": line})

    check_command = step.get("check_command")
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
            # Already satisfied — skip entirely, whether or not the step
            # is automatable. No HITL interrupt either: nothing
            # destructive is about to happen.
            writer({"type": "check_satisfied", "description": step["description"]})
            entry = asdict(check_result)
            entry["skipped_install"] = True
            return {**state, "results": [*state["results"], entry]}

    if not step.get("automatable", True):
        # Not satisfied (or unverifiable) and can't be done via CLI at
        # all — a GUI installer, an App Store login, a license
        # click-through. Never attempted: step["command"] is not
        # executable in this case by contract (see PLAN_SYSTEM_PROMPT).
        instructions = step.get("manual_instructions") or step["description"]
        writer(
            {
                "type": "manual_action_needed",
                "description": step["description"],
                "instructions": instructions,
            }
        )
        if check_result is not None:
            entry = asdict(check_result)
        else:
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
        # A failed/absent check here means "not done yet", not "an error
        # occurred" — never let this abort the whole run via verify_node.
        entry["returncode"] = 0
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
    """Runs once, only on the 'done' path (every step executed without a
    hard failure) — a single LLM call reviewing the whole run against the
    goal. Exists because a command's exit code alone doesn't prove the
    goal was achieved: `flutter doctor` exits 0 even while its own output
    reports a missing Android SDK or incomplete Xcode install."""
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
        # A malformed judge response shouldn't crash an otherwise-successful
        # run — fall back to an honest "couldn't verify" rather than
        # silently claiming success.
        assessment = {
            "achieved": False,
            "summary": "Could not parse the verification response — please review the output above manually.",
        }
    writer({"type": "judgement_ready", "assessment": assessment})
    return {**state, "assessment": assessment}
