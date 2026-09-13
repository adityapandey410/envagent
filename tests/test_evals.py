"""Runs the eval scenarios in evals/scenarios/ as a regression suite.

Plain pytest, not promptfoo: promptfoo would pull in a whole separate
Node.js toolchain for a pure-Python project, which isn't worth it for
scenarios that (so far) test deterministic logic rather than live model
output. Revisit if/when scenarios need to assert on actual LLM-generated
plans rather than the risk-gating logic itself.
"""

import json
from pathlib import Path

from envagent.hitl.gate import PlanStep, classify_step

SCENARIOS_DIR = Path(__file__).parent.parent / "evals" / "scenarios"


def _load_cases():
    cases = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        for case in data["cases"]:
            cases.append((path.name, case))
    return cases


def test_hitl_risk_gating_scenarios():
    failures = []
    for filename, case in _load_cases():
        step = PlanStep(
            description="eval scenario step",
            command=case["command"],
            risk=case["risk"],
            undo_command=None,
        )
        gated = classify_step(step) is not None
        if gated != case["expect_gated"]:
            failures.append(
                f"{filename}: {case['command']!r} expected gated={case['expect_gated']}, got {gated}"
            )
    assert not failures, "\n".join(failures)
