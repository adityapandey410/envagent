from __future__ import annotations

import ctypes
import os
import platform

_ADMIN_GROUP_NAMES = {"admin", "sudo", "wheel"}


def is_elevated() -> bool:
    if platform.system() == "Windows":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def can_elevate() -> bool:
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
