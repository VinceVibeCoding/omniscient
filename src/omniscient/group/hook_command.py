"""The command strings that omnigroup writes into Claude Code / Copilot settings.

POSIX: one shell string, paths quoted with shlex (unchanged since the first release).
Windows (see docs/omnigroup.md, « Windows natif »): Claude Code runs a hook `command`
string through Git Bash when Git for Windows is installed, else PowerShell, so no single
quoting works in both. Hooks therefore use the exec form (`command` = the executable,
`args` = its arguments: no shell, no quoting, spaces are fine); paths use forward slashes
(Windows programs accept them and JSON needs no backslash escapes). Copilot entries get a
`powershell` twin of their `bash` command. The statusLine only takes a string: a path
with spaces is shortened to its 8.3 form when possible, else double-quoted.
"""

from __future__ import annotations

import ctypes
import shlex
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omniscient.group.hooks import HOOK_SCRIPT
from omniscient.home import DEFAULT_HOME, Home

SHORT_PATH_MAX = 520
_PLAIN = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./:=@+~"
)


class HookInstallError(Exception):
    """The settings file cannot be read, understood or written."""


def is_windows() -> bool:
    return sys.platform == "win32"


def _text(path: Path | str, windows: bool) -> str:
    return Path(path).as_posix() if windows else str(path)


def base_command(
    home: Home | None = None,
    which: Callable[[str], str | None] = shutil.which,
    python: str = sys.executable,
    windows: bool | None = None,
) -> str:
    """The hook command: the absolute `omniscient-hook` script (fast start: it imports
    only the hook client, not the whole CLI), else `<python> -m omniscient.group.
    hook_client`; plus `--home` when the home is not the default."""
    win = is_windows() if windows is None else windows
    exe = which(HOOK_SCRIPT)
    if exe:
        cmd = shlex.quote(_text(Path(exe).resolve(), win))
    elif python:
        cmd = f"{shlex.quote(_text(python, win))} -m omniscient.group.hook_client"
    else:
        raise HookInstallError(
            "Commande « omniscient-hook » introuvable dans le PATH : installez "
            "Omniscient d'abord (uv tool install ...)."
        )
    if home is not None and home.root.resolve() != DEFAULT_HOME.resolve():
        cmd += f" --home {shlex.quote(_text(home.root, win))}"
    return cmd


def claude_command_entry(
    command: str, timeout: int, windows: bool | None = None
) -> dict[str, Any]:
    """A Claude `command` hook: a shell string, or the exec form on Windows."""
    if not (is_windows() if windows is None else windows):
        return {"type": "command", "command": command, "timeout": timeout}
    argv = shlex.split(command)
    return {
        "type": "command",
        "command": argv[0],
        "args": argv[1:],
        "timeout": timeout,
    }


def powershell_form(command: str) -> str:
    """The same command for PowerShell: the call operator and single-quoted paths."""
    return "& " + command


def _short_path(path: str, get: Callable[..., int] | None = None) -> str | None:
    """The 8.3 form of an existing Windows path (no spaces), or None."""
    if not is_windows() and get is None:
        return None
    fn = get or ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    buf = ctypes.create_unicode_buffer(SHORT_PATH_MAX)
    size = fn(path, buf, SHORT_PATH_MAX)
    return buf.value.replace("\\", "/") if 0 < size < SHORT_PATH_MAX else None


def _line_token(token: str, short: Callable[[str], str | None]) -> str:
    if token and set(token) <= _PLAIN:
        return token
    shortened = short(token)
    if shortened and set(shortened) <= _PLAIN:
        return shortened
    return '"' + token.replace('"', "") + '"'


def line_command(
    command: str,
    windows: bool | None = None,
    short: Callable[[str], str | None] = _short_path,
) -> str:
    """`command` as the single string a statusLine takes (unchanged on POSIX)."""
    if not (is_windows() if windows is None else windows):
        return command
    return " ".join(_line_token(t, short) for t in shlex.split(command))
