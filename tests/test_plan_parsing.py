from envagent.agent.nodes import _parse_plan

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


MISSING_COMMA_OUTPUT = (
    '[\n  {\n    "description": "Install Git"\n'
    '    "command": "brew install git",\n'
    '    "risk": "destructive",\n'
    '    "undo_command": "brew uninstall git"\n'
    "  }\n]"
)


def test_parse_plan_falls_back_for_a_missing_comma_delimiter():
    plan = _parse_plan(MISSING_COMMA_OUTPUT)
    assert plan[0]["command"] == "brew install git"
    assert plan[0]["description"] == "Install Git"
