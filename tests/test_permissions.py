from envagent.system import permissions


def test_is_elevated_true_when_root(monkeypatch):
    monkeypatch.setattr(permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(permissions.os, "geteuid", lambda: 0)
    assert permissions.is_elevated() is True


def test_is_elevated_false_when_not_root(monkeypatch):
    monkeypatch.setattr(permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(permissions.os, "geteuid", lambda: 501)
    assert permissions.is_elevated() is False


def test_can_elevate_true_when_already_elevated(monkeypatch):
    monkeypatch.setattr(permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(permissions.os, "geteuid", lambda: 0)
    assert permissions.can_elevate() is True


def test_can_elevate_true_when_in_admin_group(monkeypatch):
    import grp as real_grp

    class _FakeGroup:
        def __init__(self, name):
            self.gr_name = name

    monkeypatch.setattr(permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(permissions.os, "geteuid", lambda: 501)
    monkeypatch.setattr(permissions.os, "getgroups", lambda: [1, 2])
    monkeypatch.setattr(
        real_grp, "getgrgid", lambda gid: _FakeGroup("admin" if gid == 1 else "staff")
    )
    assert permissions.can_elevate() is True


def test_can_elevate_false_when_no_admin_group(monkeypatch):
    import grp as real_grp

    class _FakeGroup:
        def __init__(self, name):
            self.gr_name = name

    monkeypatch.setattr(permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(permissions.os, "geteuid", lambda: 501)
    monkeypatch.setattr(permissions.os, "getgroups", lambda: [20])
    monkeypatch.setattr(real_grp, "getgrgid", lambda gid: _FakeGroup("staff"))
    assert permissions.can_elevate() is False
