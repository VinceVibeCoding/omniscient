"""Finding the `claude` CLI and building a safe argv to launch it (POSIX and Windows).

On Windows `claude` is a real `claude.exe` (native installer, WinGet, and the npm package
links the same native binary). An old npm install may leave only a `claude.cmd` shim, and a
`.cmd` cannot be started without a shell: we first look for the real executable next to it
(`claude.exe`, `node_modules/@anthropic-ai/claude-code/bin/claude.exe`); if there is none,
we go through `cmd.exe /d /c` but only when every argument is plain (no metacharacter
cmd.exe could read), never `shell=True`. Nothing here ever builds a shell string.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

log = logging.getLogger(__name__)

CLAUDE_NOT_FOUND = (
    "Claude Code (« claude ») est introuvable. Installe-le (PowerShell : "
    "`irm https://claude.ai/install.ps1 | iex`), ouvre un nouveau terminal, vérifie "
    "`claude --version`, puis relance le démon."
)
SHIM_SUFFIXES = (".cmd", ".bat")
NPM_NATIVE = ("node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe")
# arguments cmd.exe can pass through untouched
SAFE_CMD_ARG = re.compile(r"^[A-Za-z0-9_.:=/\\-]*$")
Which = Callable[[str], str | None] | None


def is_windows() -> bool:
    return sys.platform == "win32"


def _native_install(environ: Mapping[str, str], windows: bool) -> Path | None:
    """The native installer's launcher (Windows only: a daemon started by the widget can
    carry a PATH older than the install), when PATH does not have it."""
    home = environ.get("USERPROFILE")
    if not windows or not home:
        return None
    path = Path(home) / ".local" / "bin" / "claude.exe"
    return path if path.is_file() else None


def find_claude(
    which: Which = None,
    environ: Mapping[str, str] | None = None,
    windows: bool | None = None,
) -> str | None:
    """The path of the `claude` command, or None."""
    win = is_windows() if windows is None else windows
    found = (which or shutil.which)("claude")
    if found:
        return found
    native = _native_install(os.environ if environ is None else environ, win)
    return str(native) if native else None


def _real_exe(shim: Path) -> Path | None:
    for candidate in (shim.with_name("claude.exe"), shim.parent.joinpath(*NPM_NATIVE)):
        if candidate.is_file():
            return candidate
    return None


def launch_prefix(path: str, windows: bool | None = None) -> tuple[str, ...]:
    """The argv prefix that starts `path` without a shell; raises ValueError for a
    `.cmd` shim with no real executable (the caller turns it into a French message)."""
    if not (is_windows() if windows is None else windows):
        return (path,)
    if not path.lower().endswith(SHIM_SUFFIXES):
        return (path,)
    real = _real_exe(Path(path))
    if real is not None:
        return (str(real),)
    return ("cmd.exe", "/d", "/c", path)


def check_shim_args(argv: Sequence[str]) -> None:
    """A cmd.exe launch only takes plain arguments (raises ValueError otherwise)."""
    if list(argv[:3]) == ["cmd.exe", "/d", "/c"]:
        bad = [a for a in argv[3:] if not SAFE_CMD_ARG.match(a)]
        if bad:
            raise ValueError("argument inattendu pour le raccourci claude.cmd")


def resolve_command(
    claude: Sequence[str],
    which: Which = None,
    environ: Mapping[str, str] | None = None,
    windows: bool | None = None,
) -> tuple[str, ...]:
    """Resolve a bare `claude` command once (logged); a configured path is kept."""
    argv = tuple(claude)
    if not argv or any(sep in argv[0] for sep in ("/", "\\")):
        return argv
    found = (
        find_claude(which, environ, windows)
        if argv[0] == "claude"
        else (which or shutil.which)(argv[0])
    )
    if found is None:
        log.warning("omnigroup chat: %s not found in the daemon PATH", argv[0])
        return argv
    prefix = launch_prefix(found, windows)
    log.info("omnigroup chat: using %s", " ".join(prefix))
    return (*prefix, *argv[1:])
