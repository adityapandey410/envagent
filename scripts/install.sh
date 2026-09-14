#!/usr/bin/env sh
# Bootstrap installer for envagent — works on a fresh macOS/Linux machine
# with nothing preinstalled except curl and internet access.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/adityapandey410/envagent/main/scripts/install.sh | sh
#
# Two stages, both needing zero Python preinstalled:
#   1. Install uv itself if missing (uv's own installer is a standalone
#      binary download, not a Python package).
#   2. `uv tool install` the repo — this also downloads/manages the right
#      Python version automatically if the system doesn't have one, then
#      installs envagent as a global command.
#
# Windows is not covered here — Phase 4 scope (see CLAUDE.md). Windows
# users can still use `uv tool install` manually once uv is installed via
# its PowerShell installer.

set -eu

REPO_URL="git+https://github.com/adityapandey410/envagent"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found — installing it first..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin by default; make it available in this
  # script's own shell immediately (the installer also updates shell rc
  # files, but that only takes effect in new sessions).
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv installation did not make 'uv' available on PATH." >&2
  echo "Try opening a new terminal and re-running this script." >&2
  exit 1
fi

echo "Installing envagent..."
uv tool install "$REPO_URL"

echo ""
echo "envagent installed. Run 'envagent init' to get started."
echo "If the 'envagent' command isn't found, open a new terminal first."
