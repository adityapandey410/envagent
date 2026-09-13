from envagent.agent.nodes import _parse_plan

# Exact raw output captured from a real live call (gpt-5.1, goal="install
# vs code") that crashed with json.JSONDecodeError before the json5
# fallback was added: the model single-quoted a command string because it
# contained a literal double quote (`bash -c "..."`), which is invalid
# strict JSON.
REAL_SINGLE_QUOTED_OUTPUT = (
    '[\n  {\n    "description": "Install Homebrew package manager",\n'
    '    "command": \'/bin/bash -c "$(curl -fsSL https://example.com/install.sh)"\',\n'
    '    "risk": "destructive",\n'
    '    "undo_command": null,\n'
    '    "check_command": "command -v brew >/dev/null 2>&1"\n'
    "  }\n]"
)


def test_parse_plan_handles_strict_json():
    plan = _parse_plan('[{"description": "d", "command": "echo hi", "risk": "safe", "undo_command": null}]')
    assert plan[0]["command"] == "echo hi"


def test_parse_plan_handles_markdown_fenced_json():
    plan = _parse_plan(
        '```json\n[{"description": "d", "command": "echo hi", "risk": "safe", "undo_command": null}]\n```'
    )
    assert plan[0]["command"] == "echo hi"


def test_parse_plan_falls_back_for_single_quoted_strings_with_embedded_double_quotes():
    plan = _parse_plan(REAL_SINGLE_QUOTED_OUTPUT)
    assert plan[0]["command"] == '/bin/bash -c "$(curl -fsSL https://example.com/install.sh)"'
