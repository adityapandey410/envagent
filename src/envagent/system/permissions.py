"""sudo/admin/UAC permission checks.

Purpose: know upfront whether the current user can even run privileged
commands, so the agent can warn before planning rather than have a plan
fail with a permission error several steps in. Best-effort — permission
models differ enough across OSes that this is a heuristic, not a
guarantee (e.g. sudo can be configured in ways group membership alone
doesn't capture).
"""

from __future__ import annotations

import ctypes
import os
import platform

_ADMIN_GROUP_NAMES = {"admin", "sudo", "wheel"}


def is_elevated() -> bool:
    """Is the current process already running as root/Administrator?"""
    if platform.system() == "Windows":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def can_elevate() -> bool:
    """Best-effort: can the current user run privileged commands at all
    (sudo on macOS/Linux, an elevated prompt on Windows)? Already being
    elevated counts as yes."""
    if is_elevated():
        return True
    if platform.system() == "Windows":
        return False
    try:
        import grp

        user_groups = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except Exception:
        return False
    return bool(user_groups & _ADMIN_GROUP_NAMES)
