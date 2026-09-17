import sys
import types

from envagent.system import executor


def test_popen_args_uses_shell_string_on_posix(monkeypatch):
    monkeypatch.setattr(executor.platform, "system", lambda: "Darwin")
    assert executor._popen_args("echo hi") == "echo hi"


def test_popen_args_uses_powershell_argv_on_windows(monkeypatch):
    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    args = executor._popen_args("Get-Command node")
    assert args[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert args[4].endswith("Get-Command node")


def test_popen_args_disables_the_slow_progress_bar_on_windows(monkeypatch):
    # Invoke-WebRequest's default progress rendering has a severe perf bug
    # on large downloads (confirmed live: looked hung for 30+ minutes) —
    # every Windows command should disable it unconditionally.
    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    args = executor._popen_args("Invoke-WebRequest -Uri $url -OutFile $out")
    assert "$ProgressPreference = 'SilentlyContinue'" in args[4]


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
    assert args[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    assert args[4].endswith("winget install Git.Git")
    assert shell is False


class _FakeRegistryKey:
    def __init__(self, hive):
        self.hive = hive

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_winreg(monkeypatch, values: dict):
    """values maps a fake hive marker -> the Path string that hive holds
    (or omit a hive to simulate its registry key not existing)."""

    def fake_open_key(hive, subkey):
        if hive not in values:
            raise OSError("key not found")
        return _FakeRegistryKey(hive)

    def fake_query_value_ex(key, name):
        return values[key.hive], 2

    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE="HKLM",
        HKEY_CURRENT_USER="HKCU",
        OpenKey=fake_open_key,
        QueryValueEx=fake_query_value_ex,
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)


def test_windows_env_with_fresh_path_merges_machine_and_user_registry_values(monkeypatch):
    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    _install_fake_winreg(
        monkeypatch,
        {"HKLM": r"C:\Windows\system32", "HKCU": r"C:\Users\test\develop\flutter\bin"},
    )
    env = executor._windows_env_with_fresh_path()
    assert r"C:\Windows\system32" in env["PATH"]
    assert r"C:\Users\test\develop\flutter\bin" in env["PATH"]


def test_windows_env_with_fresh_path_degrades_gracefully_when_a_hive_is_missing(monkeypatch):
    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    _install_fake_winreg(monkeypatch, {"HKCU": r"C:\Users\test\develop\flutter\bin"})
    env = executor._windows_env_with_fresh_path()
    assert env["PATH"] == r"C:\Users\test\develop\flutter\bin"


def test_run_command_passes_a_freshened_env_on_windows(monkeypatch):
    calls = []

    class _FakeProc:
        stdout = iter([])
        returncode = 0

        def wait(self):
            pass

    def fake_popen(args, shell, env, **kwargs):
        calls.append(env)
        return _FakeProc()

    monkeypatch.setattr(executor.platform, "system", lambda: "Windows")
    monkeypatch.setattr(executor.subprocess, "Popen", fake_popen)
    _install_fake_winreg(monkeypatch, {"HKCU": r"C:\Users\test\develop\flutter\bin"})

    executor._run_command("flutter doctor")

    assert calls[0]["PATH"] == r"C:\Users\test\develop\flutter\bin"
