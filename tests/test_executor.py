from envagent.system import executor


def test_popen_args_uses_shell_string_on_posix(monkeypatch):
    monkeypatch.setattr(executor.platform, "system", lambda: "Darwin")
    assert executor._popen_args("echo hi") == "echo hi"


def test_popen_args_uses_powershell_argv_on_windows(monkeypatch):
    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    args = executor._popen_args("Get-Command node")
    assert args == ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Command node"]


def test_run_command_passes_shell_true_only_for_a_string_command(monkeypatch):
    calls = []

    class _FakeProc:
        stdout = iter([])
        returncode = 0

        def wait(self):
            pass

    def fake_popen(args, shell, **kwargs):
        calls.append((args, shell))
        return _FakeProc()

    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    executor._run_command("winget install Git.Git")

    assert len(calls) == 1
    args, shell = calls[0]
    assert args == [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "winget install Git.Git",
    ]
    assert shell is False
