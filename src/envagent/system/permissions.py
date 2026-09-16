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

_win32_prototypes_configured = False


def _configure_win32_prototypes() -> None:
    """Explicitly declare argtypes/restype for every Win32 call below.

    A previous version of this code relied on ctypes' untyped defaults
    (every foreign-function argument/return value treated as a 4-byte
    `c_int` unless told otherwise). That silently truncated
    GetCurrentProcess()'s pointer-sized pseudo-handle return value on
    64-bit Windows, which made OpenProcessToken fail and made this whole
    check fall back to the exact broken behavior it was meant to fix —
    confirmed live on a real Windows 11 machine (see CLAUDE.md). Declaring
    real prototypes (HANDLE/DWORD/BOOL, not bare ints) removes that whole
    class of silent-truncation bug rather than fixing one instance of it."""
    global _win32_prototypes_configured
    if _win32_prototypes_configured:
        return
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL

    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL

    advapi32.CheckTokenMembership.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.BOOL),
    ]
    advapi32.CheckTokenMembership.restype = wintypes.BOOL

    _win32_prototypes_configured = True


def _check_token_membership_in_admins(h_token: int | None) -> bool:
    """Runs CheckTokenMembership for the Administrators SID against a
    specific token (or the current thread/process token, if h_token is
    None/0)."""
    sid_ptr = wintypes.LPVOID()
    if not ctypes.windll.advapi32.ConvertStringSidToSidW(
        _WINDOWS_ADMINISTRATORS_SID, ctypes.byref(sid_ptr)
    ):
        return False
    try:
        is_member = wintypes.BOOL()
        if not ctypes.windll.advapi32.CheckTokenMembership(
            h_token, sid_ptr, ctypes.byref(is_member)
        ):
            return False
        return bool(is_member.value)
    finally:
        ctypes.windll.kernel32.LocalFree(sid_ptr)


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
    _configure_win32_prototypes()
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
