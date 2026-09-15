from envagent.hitl.gate import PlanStep, classify_step, is_diagnostic_step


def _step(command: str, risk: str = "safe") -> PlanStep:
    return PlanStep(description="test step", command=command, risk=risk, undo_command=None)


def test_safe_step_with_no_dangerous_keywords_is_not_gated():
    assert classify_step(_step("flutter doctor")) is None


def test_explicit_destructive_risk_is_always_gated():
    assert classify_step(_step("echo hi", risk="destructive")) is not None


def test_safety_net_overrides_a_mislabeled_safe_step():
    step = _step("sudo apt install android-sdk", risk="safe")
    interrupt = classify_step(step)
    assert interrupt is not None
    assert interrupt["type"] == "confirm"


def test_confirm_message_includes_the_command_and_description():
    interrupt = classify_step(_step("rm -rf /tmp/foo", risk="destructive"))
    assert interrupt is not None
    assert "rm -rf /tmp/foo" in interrupt["message"]
    assert "test step" in interrupt["message"]


def test_flutter_doctor_style_step_is_recognized_as_diagnostic():
    step = PlanStep(
        description="Run Flutter doctor to verify installation",
        command="flutter doctor -v",
        risk="safe",
        undo_command=None,
        check_command="flutter doctor -v >/dev/null 2>&1",
    )
    assert is_diagnostic_step(step) is True


def test_an_ordinary_install_step_is_not_flagged_diagnostic():
    step = _step("brew install --cask flutter")
    assert is_diagnostic_step(step) is False


def test_usermod_group_change_is_gated():
    step = _step("sudo usermod -aG docker $USER")
    interrupt = classify_step(step)
    assert interrupt is not None


def test_pip_check_is_recognized_as_diagnostic():
    step = PlanStep(
        description="Verify installed packages have compatible dependencies",
        command="pip check",
        risk="safe",
        undo_command=None,
    )
    assert is_diagnostic_step(step) is True
