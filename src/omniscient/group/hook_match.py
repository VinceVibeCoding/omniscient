"""Recognising omniscient's own hook commands in agent settings (exact argv match)."""

from __future__ import annotations

import re
import shlex
from typing import Any

from omniscient.group.hooks import HOOK_SCRIPT

STATUS_FLAG = "--statusline"


def _argv(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def exe_name(path: str) -> str:
    """The program name of a path (either separator), without a Windows extension."""
    name = re.split(r"[\\/]", path)[-1]
    return re.sub(r"\.(exe|cmd|bat)$", "", name, flags=re.IGNORECASE)


def is_our_argv(argv: list[str]) -> bool:
    """Exactly our client: `…/omniscient-hook …`, `<python> -m omniscient.group.
    hook_client …` or `…/omniscient group hook …` (never a mere mention of it).
    A leading `&` (the PowerShell call operator) is ignored."""
    if argv and argv[0] == "&":
        argv = argv[1:]
    if not argv:
        return False
    exe = exe_name(argv[0])
    if exe == HOOK_SCRIPT or argv[1:3] == ["-m", "omniscient.group.hook_client"]:
        return True
    return exe == "omniscient" and argv[1:3] == ["group", "hook"]


def is_our_command(command: str) -> bool:
    return is_our_argv(_argv(command))


def is_status_command(command: str) -> bool:
    """Claude's statusLine runs our client (`omniscient-hook --statusline` or legacy)."""
    argv = _argv(command)
    legacy = bool(argv) and exe_name(argv[0]) == "omniscient"
    if legacy and argv[1:3] == ["group", "statusline"]:
        return True
    return STATUS_FLAG in argv and is_our_command(command)


def is_ours(entry: Any) -> bool:
    """A hook entry (or a Claude matcher group) that runs our command."""
    if not isinstance(entry, dict):
        return False
    args = entry.get("args")
    command = entry.get("command")
    exec_form = isinstance(command, str) and isinstance(args, list)
    if exec_form and all(isinstance(a, str) for a in args) and is_our_argv([command, *args]):  # fmt: skip
        return True
    return any(
        isinstance(entry.get(key), str) and is_our_command(entry[key])
        for key in ("command", "bash", "powershell")
    )


def without_ours(hooks: dict[str, Any]) -> dict[str, Any]:
    """Claude `hooks` with our commands removed (emptied groups and events dropped)."""
    out: dict[str, Any] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept = []
        for group in groups:
            if is_ours(group):  # a flat Copilot entry
                continue
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept.append(group)
                continue
            mine = [h for h in inner if is_ours(h)]
            if not mine:
                kept.append(group)
            elif len(mine) < len(inner):
                kept.append({**group, "hooks": [h for h in inner if not is_ours(h)]})
        if kept:
            out[event] = kept
    return out
