"""OS/arch/package-manager detection.

Replaces the Phase-1 stopgap (nodes._describe_os, a plain string) with
structured detection. The `os_key` is the important addition: it matches
the OS-selector class-naming convention used by real docs sites (e.g.
Flutter's `{: .steps .macos-only}` markers), so doc extraction can key
off the same value used for planning.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass

_OS_KEYS = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}
_OS_NAMES = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}

# Package managers we know how to detect, in preference order per OS.
_CANDIDATE_MANAGERS: dict[str, list[str]] = {
    "macos": ["brew"],
    "linux": ["apt", "dnf", "pacman", "zypper", "snap"],
    "windows": ["winget", "choco"],
}


@dataclass
class SystemInfo:
    os_key: str
    """Canonical key: 'macos' | 'linux' | 'windows' (falls back to the
    lowercased platform.system() value on anything else)."""
    os_name: str
    arch: str
    release: str
    package_managers: list[str]
    """Which candidate package managers are actually on PATH, in
    preference order. May be empty (e.g. a fresh Linux box with none)."""

    def describe(self) -> str:
        pm = f", package manager: {self.package_managers[0]}" if self.package_managers else ""
        return f"{self.os_name} ({self.arch}, release {self.release}){pm}"


def detect_system() -> SystemInfo:
    system = platform.system()
    os_key = _OS_KEYS.get(system, system.lower())
    os_name = _OS_NAMES.get(system, system)
    managers = [m for m in _CANDIDATE_MANAGERS.get(os_key, []) if shutil.which(m)]
    return SystemInfo(
        os_key=os_key,
        os_name=os_name,
        arch=platform.machine(),
        release=platform.release(),
        package_managers=managers,
    )
