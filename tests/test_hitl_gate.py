from envagent.hitl.gate import PlanStep, classify_step


def _step(command: str, risk: str = "safe") -> PlanStep:
    return PlanStep(description="test step", command=command, risk=risk, undo_command=None)


def test_safe_step_with_no_dangerous_keywords_is_not_gated():
    assert classify_step(_step("flutter doctor")) is None


def test_explicit_destructive_risk_is_always_gated():
    assert classify_step(_step("echo hi", risk="destructive")) is not None


def test_safety_net_overrides_a_mislabeled_safe_step():
    # Even if a plan-generating LLM mislabels this "safe", the keyword
    # safety net must still gate it. This is the behavior the "HITL is a
    # hard gate, not a suggestion" principle depends on.
    step = _step("sudo apt install android-sdk", risk="safe")
    interrupt = classify_step(step)
    assert interrupt is not None
    assert interrupt["type"] == "confirm"


def test_confirm_message_includes_the_command_and_description():
    interrupt = classify_step(_step("rm -rf /tmp/foo", risk="destructive"))
    assert interrupt is not None
    assert "rm -rf /tmp/foo" in interrupt["message"]
    assert "test step" in interrupt["message"]
