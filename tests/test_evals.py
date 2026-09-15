import json
from pathlib import Path

from envagent.hitl.gate import PlanStep, classify_step
from envagent.recipes.registry import match_recipe

SCENARIOS_DIR = Path(__file__).parent.parent / "evals" / "scenarios"


def _load_cases(filename: str):
    data = json.loads((SCENARIOS_DIR / filename).read_text())
    return data["cases"]


def test_hitl_risk_gating_scenarios():
    failures = []
    for case in _load_cases("hitl_risk_gating.json"):
        step = PlanStep(
            description="eval scenario step",
            command=case["command"],
            risk=case["risk"],
            undo_command=None,
        )
        gated = classify_step(step) is not None
        if gated != case["expect_gated"]:
            failures.append(
                f"{case['command']!r} expected gated={case['expect_gated']}, got {gated}"
            )
    assert not failures, "\n".join(failures)


def test_recipe_matching_scenarios():
    failures = []
    for case in _load_cases("recipe_matching.json"):
        recipe = match_recipe(case["goal"])
        matched_name = recipe.name if recipe is not None else None
        if matched_name != case["expected_recipe"]:
            failures.append(
                f"{case['goal']!r} expected recipe={case['expected_recipe']!r}, got {matched_name!r}"
            )
    assert not failures, "\n".join(failures)
