"""CLI-level test that real-time per-step command visibility actually
works, not just the underlying graph mechanics (already covered by
test_graph.py). Uses Typer's CliRunner; questionary rendering is stubbed
out since it needs a real TTY, which the test runner doesn't provide.
"""

import json

from typer.testing import CliRunner

from envagent.agent.prompts import JUDGE_SYSTEM_PROMPT
from envagent.cli import app

PLAN = [
    {
        "description": "print a greeting",
        "command": "echo hello",
        "risk": "safe",
        "undo_command": None,
    },
    {
        "description": "pretend to install something",
        "command": "echo installing",
        "risk": "destructive",
        "undo_command": "echo uninstalling",
    },
]

JUDGEMENT = {"achieved": True, "summary": "Both steps completed successfully."}


class _FakeProvider:
    def __init__(self, plan=PLAN):
        self._plan = plan

    def complete(self, api_key: str, system: str, user: str) -> str:
        if system == JUDGE_SYSTEM_PROMPT:
            return json.dumps(JUDGEMENT)
        return json.dumps(self._plan)


def _patch_env(monkeypatch, tmp_path, plan=PLAN):
    monkeypatch.setattr(
        "envagent.agent.checkpointer.user_data_dir", lambda _app: str(tmp_path / "data")
    )
    monkeypatch.setattr(
        "envagent.system.executor.user_log_dir", lambda _app: str(tmp_path / "logs")
    )
    monkeypatch.setattr(
        "envagent.config.settings.user_config_dir", lambda _app: str(tmp_path / "config")
    )
    monkeypatch.setattr(
        "envagent.agent.nodes._active_provider_and_key",
        lambda: (_FakeProvider(plan), "fake-key"),
    )
    # Bypass questionary entirely: always approve any interrupt.
    monkeypatch.setattr("envagent.cli._render_interrupt", lambda payload: True)


def test_setup_prints_every_step_as_it_runs_not_just_the_gated_one(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "test goal"])

    assert result.exit_code == 0, result.output
    assert "$ echo hello" in result.output
    assert "hello" in result.output  # the safe step's own stdout, printed live
    assert "$ echo installing" in result.output
    assert "Goal achieved:" in result.output
    assert "Both steps completed successfully." in result.output


FAILING_PLAN = [
    {
        "description": "a command whose real error gets redirected away",
        "command": "echo this goes to stderr, not stdout >&2; false",
        "risk": "safe",
        "undo_command": None,
    },
]


def test_failed_step_shows_command_and_exit_code_not_just_a_bare_message(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=FAILING_PLAN)
    runner = CliRunner()

    result = runner.invoke(app, ["setup", "test goal"])

    assert result.exit_code == 0, result.output
    assert "Step failed:" in result.output
    assert "echo this goes to stderr, not stdout >&2; false" in result.output
    assert "exited with code" in result.output
    assert "1" in result.output
    assert "Setup stopped" in result.output
