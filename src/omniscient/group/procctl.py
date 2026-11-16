"""Child-process control that works on POSIX and on native Windows (no shell, argv only).

POSIX: the child gets its own session, signals go to its process group (SIGINT first,
SIGTERM then SIGKILL). Windows: the child gets its own process group and no console
window; "interrupt" is CTRL_BREAK_EVENT, "terminate" and "kill" are `taskkill /T`
(/F for kill) so the whole tree goes, since Windows has no process-group signals.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

log = logging.getLogger(__name__)

TASKKILL_TIMEOUT_S = 10.0
CREATE_NEW_PROCESS_GROUP = 0x00000200  # winbase.h, named here so it exists everywhere
CREATE_NO_WINDOW = 0x08000000
Run = Callable[..., Any]


def is_windows() -> bool:
    return sys.platform == "win32"


def spawn_kwargs(windows: bool | None = None) -> dict[str, Any]:
    """Popen keywords that put the child in its own group/session."""
    if windows if windows is not None else is_windows():
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}
    return {"start_new_session": True}


def taskkill_argv(pid: int, force: bool) -> list[str]:
    return ["taskkill", "/T", *(["/F"] if force else []), "/PID", str(int(pid))]


def _taskkill(pid: int, force: bool, run: Run) -> None:
    try:
        run(
            taskkill_argv(pid, force),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=TASKKILL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning("omnigroup: taskkill failed for pid %s", pid, exc_info=True)


def _interrupt_windows(proc: subprocess.Popen[Any]) -> None:
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
    except (OSError, ValueError):
        log.info("omnigroup: CTRL_BREAK_EVENT not delivered to pid %s", proc.pid)


def _posix_signal(proc: subprocess.Popen[Any], sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)  # type: ignore[attr-defined]
    except (ProcessLookupError, PermissionError):
        return
    except OSError:
        log.exception("omnigroup: signal %s failed", sig)


def interrupt(proc: subprocess.Popen[Any] | None) -> None:
    """Ask the process (tree) to stop its current work: SIGINT / CTRL_BREAK."""
    if proc is None or proc.poll() is not None:
        return
    if is_windows():
        _interrupt_windows(proc)
    else:
        _posix_signal(proc, signal.SIGINT)


def terminate(proc: subprocess.Popen[Any] | None, run: Run = subprocess.run) -> None:
    """Ask the process tree to exit: SIGTERM / `taskkill /T`."""
    if proc is None or proc.poll() is not None:
        return
    if is_windows():
        _taskkill(proc.pid, False, run)
    else:
        _posix_signal(proc, signal.SIGTERM)


def kill(proc: subprocess.Popen[Any] | None, run: Run = subprocess.run) -> None:
    """Force the process tree to exit: SIGKILL / `taskkill /T /F`."""
    if proc is None or proc.poll() is not None:
        return
    if is_windows():
        _taskkill(proc.pid, True, run)
    else:
        _posix_signal(proc, getattr(signal, "SIGKILL", signal.SIGTERM))


def stop_ladder() -> Sequence[Callable[[subprocess.Popen[Any] | None], None]]:
    """The escalation after the first interrupt: terminate, then kill."""
    return (terminate, kill)
