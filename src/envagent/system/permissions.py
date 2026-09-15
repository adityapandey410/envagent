from __future__ import annotations

import ctypes
import os
import platform
from ctypes import wintypes

_ADMIN_GROUP_NAMES = {"admin", "sudo", "wheel"}


def is_elevated() -> bool:
    if platform.system() == "Windows":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


_WINDOWS_ADMINISTRATORS_SID = "S-1-5-32-544"
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION_TYPE = 18  # TOKEN_INFORMATION_CLASS::TokenElevationType
_TOKEN_LINKED_TOKEN = 19  # TOKEN_INFORMATION_CLASS::TokenLinkedToken
_TOKEN_ELEVATION_TYPE_LIMITED = 3


def _check_token_membership_in_admins(h_token: int | None) -> bool:
    """Runs CheckTokenMembership for the Administrators SID against a
    specific token (or the current thread/process token, if h_token is
    None/0)."""
    sid = ctypes.create_unicode_buffer(_WINDOWS_ADMINISTRATORS_SID)
    psid = ctypes.c_void_p()
    if not ctypes.windll.advapi32.ConvertStringSidToSidW(sid, ctypes.byref(psid)):
        return False
    try:
        is_member = ctypes.c_int()  # Win32 BOOL is a 4-byte int, not a 1-byte bool
        if not ctypes.windll.advapi32.CheckTokenMembership(
            h_token, psid, ctypes.byref(is_member)
        ):
            return False
        return bool(is_member.value)
    finally:
        ctypes.windll.kernel32.LocalFree(psid)


def _windows_is_admin_group_member() -> bool:
    """Best-effort check for local Administrators-group membership, using
    the standard Win32 CheckTokenMembership approach (distinct from
    IsUserAnAdmin, which only reflects *current* elevation, not whether
    the user could elevate via a UAC prompt).

    CheckTokenMembership against the *current* token isn't enough on its
    own: under UAC, a non-elevated process belonging to an admin user runs
    with a filtered/"limited" token where the Administrators SID is
    present but disabled — so a naive check incorrectly reports a real
    admin as unable to elevate (confirmed live: this was wrong for an
    actual admin account on a real Windows 11 machine). The fix is to
    detect a limited token via TokenElevationType and, when found, check
    membership against its *linked* (full-rights) token instead."""
    h_token = wintypes.HANDLE()
    if not ctypes.windll.advapi32.OpenProcessToken(
        ctypes.windll.kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(h_token)
    ):
        return _check_token_membership_in_admins(None)
    try:
        elevation_type = wintypes.DWORD()
        ret_len = wintypes.DWORD()
        got_elevation_type = ctypes.windll.advapi32.GetTokenInformation(
            h_token,
            _TOKEN_ELEVATION_TYPE,
            ctypes.byref(elevation_type),
            ctypes.sizeof(elevation_type),
            ctypes.byref(ret_len),
        )
        if got_elevation_type and elevation_type.value == _TOKEN_ELEVATION_TYPE_LIMITED:
            linked_token = wintypes.HANDLE()
            ret_len = wintypes.DWORD()
            if ctypes.windll.advapi32.GetTokenInformation(
                h_token,
                _TOKEN_LINKED_TOKEN,
                ctypes.byref(linked_token),
                ctypes.sizeof(linked_token),
                ctypes.byref(ret_len),
            ):
                try:
                    return _check_token_membership_in_admins(linked_token)
                finally:
                    ctypes.windll.kernel32.CloseHandle(linked_token)
        return _check_token_membership_in_admins(h_token)
    finally:
        ctypes.windll.kernel32.CloseHandle(h_token)


def can_elevate() -> bool:
    if is_elevated():
        return True
    if platform.system() == "Windows":
        try:
            return _windows_is_admin_group_member()
        except Exception:
            return False
    try:
        import grp

        user_groups = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except Exception:
        return False
    return bool(user_groups & _ADMIN_GROUP_NAMES)
