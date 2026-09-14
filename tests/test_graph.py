import json

import pytest
from langgraph.types import Command

from envagent.agent.graph import build_graph
from envagent.agent.nodes import NoStepsPlannedError
from envagent.agent.prompts import JUDGE_SYSTEM_PROMPT

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
    def __init__(self, plan=PLAN, judgement=None):
        self._plan = plan
        self._judgement = judgement or {"achieved": True, "summary": "All steps completed."}

    def complete(self, api_key: str, system: str, user: str) -> str:
        if system == JUDGE_SYSTEM_PROMPT:
            return json.dumps(self._judgement)
        return json.dumps(self._plan)


def _patch_env(monkeypatch, tmp_path, plan=PLAN, judgement=None):
    monkeypatch.setattr(
        "envagent.agent.checkpointer.user_data_dir", lambda _app: str(tmp_path / "data")
    )
    monkeypatch.setattr(
        "envagent.system.executor.user_log_dir", lambda _app: str(tmp_path / "logs")
    )
    monkeypatch.setattr(
        "envagent.agent.nodes._active_provider_and_key",
        lambda: (_FakeProvider(plan, judgement), "fake-key"),
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
    assert len(result["results"]) == 1


def test_step_already_satisfied_is_skipped_without_hitl(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=PLAN_ALREADY_SATISFIED)
    graph = build_graph()
    config = {"configurable": {"thread_id": "idempotent-thread"}}

    result = graph.invoke({"goal": "test goal", "status": "planning"}, config)

    assert "__interrupt__" not in result
    assert result["status"] == "done"
    assert len(result["results"]) == 1
    entry = result["results"][0]
    assert entry["skipped_install"] is True
    assert entry["kind"] == "check"
    assert "THIS_SHOULD_NEVER_RUN" not in entry["stdout"]


def test_resume_works_from_a_freshly_built_graph_instance(monkeypatch, tmp_path):
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


def test_irrelevant_goal_raises_a_clear_error_instead_of_crashing(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=[])
    graph = build_graph()
    config = {"configurable": {"thread_id": "irrelevant-goal-thread"}}

    with pytest.raises(NoStepsPlannedError):
        graph.invoke({"goal": "what is the capital of France?", "status": "planning"}, config)


SAFE_SINGLE_STEP_PLAN = [
    {
        "description": "check flutter setup",
        "command": "echo hi",
        "risk": "safe",
        "undo_command": None,
    },
]


def test_judge_catches_a_flutter_doctor_style_false_success(monkeypatch, tmp_path):
    _patch_env(
        monkeypatch,
        tmp_path,
        plan=SAFE_SINGLE_STEP_PLAN,
        judgement={
            "achieved": False,
            "summary": "Android SDK is missing and the Xcode install is incomplete.",
        },
    )
    graph = build_graph()
    config = {"configurable": {"thread_id": "judge-catches-false-success"}}

    result = graph.invoke(
        {"goal": "set up a generic dev environment", "status": "planning"}, config
    )

    assert result["status"] == "done"
    # The judge is what catches that "done" isn't the same as "achieved".
    assert result["assessment"]["achieved"] is False
    assert "Android SDK" in result["assessment"]["summary"]


def test_judge_confirms_a_genuine_success(monkeypatch, tmp_path):
    _patch_env(
        monkeypatch,
        tmp_path,
        plan=SAFE_SINGLE_STEP_PLAN,
        judgement={"achieved": True, "summary": "Everything is installed and working."},
    )
    graph = build_graph()
    config = {"configurable": {"thread_id": "judge-confirms-success"}}

    result = graph.invoke({"goal": "check my dev tools", "status": "planning"}, config)

    assert result["status"] == "done"
    assert result["assessment"]["achieved"] is True


MANUAL_STEP_NO_CHECK_PLAN = [
    {
        "description": "Install Xcode",
        "command": "echo SHOULD_NEVER_RUN",  # defensive: contract says "" — must never execute regardless
        "risk": "destructive",
        "undo_command": None,
        "automatable": False,
        "manual_instructions": "Open the App Store, sign in, and install Xcode.",
    },
]

MANUAL_STEP_WITH_FAILING_CHECK_PLAN = [
    {
        "description": "Install Xcode",
        "command": "echo SHOULD_NEVER_RUN",
        "risk": "destructive",
        "undo_command": None,
        "check_command": "false",  # always "not yet satisfied"
        "automatable": False,
        "manual_instructions": "Open the App Store, sign in, and install Xcode.",
    },
]

MANUAL_STEP_WITH_PASSING_CHECK_PLAN = [
    {
        "description": "Install Xcode",
        "command": "echo SHOULD_NEVER_RUN",
        "risk": "destructive",
        "undo_command": None,
        "check_command": "true",  # already satisfied
        "automatable": False,
        "manual_instructions": "Open the App Store, sign in, and install Xcode.",
    },
]


def test_non_automatable_step_with_no_check_asks_for_confirmation(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=MANUAL_STEP_NO_CHECK_PLAN)
    graph = build_graph()
    config = {"configurable": {"thread_id": "manual-step-no-check"}}

    result = graph.invoke({"goal": "install xcode", "status": "planning"}, config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "confirm"
    assert "App Store" in payload["message"]

    result = graph.invoke(Command(resume=True), config)

    assert result["status"] == "done"
    entry = result["results"][0]
    assert entry["needs_manual_action"] is True
    assert "App Store" in entry["manual_instructions"]
    # The command must genuinely never have run.
    assert "SHOULD_NEVER_RUN" not in entry["stdout"]


def test_non_automatable_step_declined_stops_the_run(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=MANUAL_STEP_NO_CHECK_PLAN)
    graph = build_graph()
    config = {"configurable": {"thread_id": "manual-step-declined"}}

    result = graph.invoke({"goal": "install xcode", "status": "planning"}, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=False), config)

    assert result["status"] == "failed"
    assert len(result["results"]) == 0


def test_non_automatable_step_confirmed_but_recheck_still_fails_stops_the_run(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=MANUAL_STEP_WITH_FAILING_CHECK_PLAN)
    graph = build_graph()
    config = {"configurable": {"thread_id": "manual-step-failing-check"}}

    result = graph.invoke({"goal": "install xcode", "status": "planning"}, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume=True), config)

    assert result["status"] == "failed"


def test_non_automatable_step_with_passing_check_is_satisfied_not_manual(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=MANUAL_STEP_WITH_PASSING_CHECK_PLAN)
    graph = build_graph()
    config = {"configurable": {"thread_id": "manual-step-passing-check"}}

    result = graph.invoke({"goal": "install xcode", "status": "planning"}, config)

    assert result["status"] == "done"
    entry = result["results"][0]
    assert entry.get("skipped_install") is True
    assert "needs_manual_action" not in entry


DIAGNOSTIC_STEP_WITH_CHECK_PLAN = [
    {
        "description": "Run Flutter doctor to verify installation",
        "command": "echo REAL_DIAGNOSTIC_OUTPUT",
        "risk": "safe",
        "undo_command": None,
        "check_command": "true",  # would otherwise always "succeed" and skip
    },
]


def test_diagnostic_step_ignores_its_own_check_command_and_always_runs(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=DIAGNOSTIC_STEP_WITH_CHECK_PLAN)
    graph = build_graph()
    config = {"configurable": {"thread_id": "diagnostic-step-override"}}

    result = graph.invoke({"goal": "test goal", "status": "planning"}, config)

    assert result["status"] == "done"
    entry = result["results"][0]
    assert entry.get("skipped_install") is not True
    assert "REAL_DIAGNOSTIC_OUTPUT" in entry["stdout"]


class _FakeIdeChoice:
    def __init__(self, message, options):
        self.message = message
        self.options = options


class _FakeRecipe:
    def __init__(self, name, doc_url, ide_choice=None):
        self.name = name
        self.doc_url = doc_url
        self.ide_choice = ide_choice


def _patch_recipe_and_docs(monkeypatch, recipe, doc_content="fake doc content"):
    monkeypatch.setattr("envagent.agent.nodes.match_recipe", lambda goal: recipe)
    monkeypatch.setattr("envagent.agent.nodes.fetch_doc", lambda url: doc_content)
    monkeypatch.setattr(
        "envagent.agent.nodes.extract_os_section", lambda content, os_key: content
    )


def test_recipe_match_with_ide_choice_raises_a_select_interrupt(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=PLAN)
    recipe = _FakeRecipe(
        name="flutter",
        doc_url="https://example.com/install",
        ide_choice=_FakeIdeChoice("Which IDE?", ["VS Code", "Android Studio"]),
    )
    _patch_recipe_and_docs(monkeypatch, recipe)
    graph = build_graph()
    config = {"configurable": {"thread_id": "recipe-ide-choice"}}

    result = graph.invoke({"goal": "install flutter", "status": "planning"}, config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "select"
    assert payload["options"] == ["VS Code", "Android Studio"]


def test_recipe_match_grounds_the_planning_prompt_in_fetched_doc_content(monkeypatch, tmp_path):
    captured_prompts = []

    class _CapturingProvider:
        def complete(self, api_key, system, user):
            captured_prompts.append(user)
            return json.dumps(PLAN)

    monkeypatch.setattr(
        "envagent.agent.checkpointer.user_data_dir", lambda _app: str(tmp_path / "data")
    )
    monkeypatch.setattr(
        "envagent.system.executor.user_log_dir", lambda _app: str(tmp_path / "logs")
    )
    monkeypatch.setattr(
        "envagent.agent.nodes._active_provider_and_key",
        lambda: (_CapturingProvider(), "fake-key"),
    )
    recipe = _FakeRecipe(name="flutter", doc_url="https://example.com/install", ide_choice=None)
    _patch_recipe_and_docs(monkeypatch, recipe, doc_content="UNIQUE_MARKER_FROM_REAL_DOCS")
    graph = build_graph()
    config = {"configurable": {"thread_id": "recipe-grounding"}}

    graph.invoke({"goal": "install flutter", "status": "planning"}, config)

    assert any("UNIQUE_MARKER_FROM_REAL_DOCS" in p for p in captured_prompts)


def test_plan_prompt_warns_the_model_when_user_cannot_elevate(monkeypatch, tmp_path):
    captured_prompts = []

    class _CapturingProvider:
        def complete(self, api_key, system, user):
            captured_prompts.append(user)
            return json.dumps(PLAN)

    monkeypatch.setattr(
        "envagent.agent.checkpointer.user_data_dir", lambda _app: str(tmp_path / "data")
    )
    monkeypatch.setattr(
        "envagent.system.executor.user_log_dir", lambda _app: str(tmp_path / "logs")
    )
    monkeypatch.setattr(
        "envagent.agent.nodes._active_provider_and_key",
        lambda: (_CapturingProvider(), "fake-key"),
    )
    monkeypatch.setattr("envagent.agent.nodes.can_elevate", lambda: False)
    graph = build_graph()
    config = {"configurable": {"thread_id": "no-elevation"}}

    graph.invoke({"goal": "test goal", "status": "planning"}, config)

    assert any("cannot run privileged" in p for p in captured_prompts)


def test_ide_choice_is_not_asked_again_on_resume(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, plan=PLAN)
    recipe = _FakeRecipe(
        name="flutter",
        doc_url="https://example.com/install",
        ide_choice=_FakeIdeChoice("Which IDE?", ["VS Code", "Android Studio"]),
    )
    _patch_recipe_and_docs(monkeypatch, recipe)
    graph = build_graph()
    config = {"configurable": {"thread_id": "recipe-ide-choice-resume"}}

    result = graph.invoke({"goal": "install flutter", "status": "planning"}, config)
    assert "__interrupt__" in result

    result = graph.invoke(Command(resume="VS Code"), config)
    if "__interrupt__" in result:
        assert result["__interrupt__"][0].value["type"] != "select"
