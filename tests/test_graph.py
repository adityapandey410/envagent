import json

from langgraph.types import Command

from envagent.agent.graph import build_graph

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

PLAN_ALREADY_SATISFIED = [
    {
        "description": "install something that is already present",
        "command": "echo THIS_SHOULD_NEVER_RUN",
        "risk": "destructive",
        "undo_command": None,
        "check_command": "echo already-there",
    },
]


class _FakeProvider:
    def __init__(self, plan=PLAN):
        self._plan = plan

    def complete(self, api_key: str, system: str, user: str) -> str:
        return json.dumps(self._plan)


def _patch_env(monkeypatch, tmp_path, plan=PLAN):
    monkeypatch.setattr(
        "envagent.agent.checkpointer.user_data_dir", lambda _app: str(tmp_path / "data")
    )
    monkeypatch.setattr(
        "envagent.system.executor.user_log_dir", lambda _app: str(tmp_path / "logs")
    )
    monkeypatch.setattr(
        "envagent.agent.nodes._active_provider_and_key",
        lambda: (_FakeProvider(plan), "fake-key"),
    )


def test_graph_pauses_on_destructive_step_and_completes_on_approval(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    graph = build_graph()
    config = {"configurable": {"thread_id": "approve-thread"}}

    result = graph.invoke({"goal": "test goal", "status": "planning"}, config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "confirm"
    assert "echo installing" in payload["message"]

    result = graph.invoke(Command(resume=True), config)

    assert result["status"] == "done"
    assert len(result["results"]) == 2
    assert result["results"][0]["stdout"].strip() == "hello"
    assert result["results"][1]["stdout"].strip() == "installing"


def test_graph_stops_without_executing_on_rejection(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    graph = build_graph()
    config = {"configurable": {"thread_id": "reject-thread"}}

    result = graph.invoke({"goal": "test goal", "status": "planning"}, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=False), config)

    assert result["status"] == "failed"
    # The safe first step already ran (no confirm needed); the destructive
    # second step was declined before ever executing.
    assert len(result["results"]) == 1


def test_step_already_satisfied_is_skipped_without_hitl(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=PLAN_ALREADY_SATISFIED)
    graph = build_graph()
    config = {"configurable": {"thread_id": "idempotent-thread"}}

    result = graph.invoke({"goal": "test goal", "status": "planning"}, config)

    # No interrupt at all: a satisfied check means nothing destructive is
    # about to happen, so there's nothing to confirm.
    assert "__interrupt__" not in result
    assert result["status"] == "done"
    assert len(result["results"]) == 1
    entry = result["results"][0]
    assert entry["skipped_install"] is True
    assert entry["kind"] == "check"
    # The step's own (destructive) command must never have run.
    assert "THIS_SHOULD_NEVER_RUN" not in entry["stdout"]


def test_resume_works_from_a_freshly_built_graph_instance(monkeypatch, tmp_path):
    """Simulates the terminal-closed-while-paused scenario: the graph
    object that hit the interrupt is discarded entirely, and a brand new
    one (same checkpoint DB, same thread_id) picks the run back up."""
    _patch_env(monkeypatch, tmp_path)
    config = {"configurable": {"thread_id": "resume-thread"}}

    first_graph = build_graph()
    paused = first_graph.invoke({"goal": "test goal", "status": "planning"}, config)
    assert "__interrupt__" in paused
    del first_graph  # simulate the process dying here

    second_graph = build_graph()
    state = second_graph.get_state(config)
    assert state.next == ("execute",)

    result = second_graph.invoke(Command(resume=True), config)
    assert result["status"] == "done"
    assert len(result["results"]) == 2
