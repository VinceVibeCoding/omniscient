"""Child-process control that works on POSIX and on native Windows (no shell, argv only).

POSIX: the child gets its own session, signals go to its process group (SIGINT first,
SIGTERM then SIGKILL). Windows: the child gets its own process group and no console
window; every stop is `taskkill /T` (/F to force), so the whole tree goes: Windows has
no process-group signals and CTRL_BREAK_EVENT cannot reach a hidden child.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from typing import Any

log = logging.getLogger(__name__)

TASKKILL_TIMEOUT_S = 10.0
CREATE_NEW_PROCESS_GROUP = 0x00000200  # winbase.h, named here so it exists everywhere
CREATE_NO_WINDOW = 0x08000000
Run = Callable[..., Any]


def is_windows() -> bool:
    return sys.platform == "win32"


def spawn_kwargs(windows: bool | None = None, hidden: bool = True) -> dict[str, Any]:
    """Popen keywords that put the child in its own group/session. `hidden` (Windows):
    no console window, which also means CTRL_BREAK cannot reach the child (its console
    is not ours): it is for children of a daemon that has no console."""
    if windows if windows is not None else is_windows():
        flags = CREATE_NEW_PROCESS_GROUP | (CREATE_NO_WINDOW if hidden else 0)
        return {"creationflags": flags}
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


def _posix_signal(proc: subprocess.Popen[Any], sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)  # type: ignore[attr-defined]
    except (ProcessLookupError, PermissionError):
        return
    except OSError:
        log.exception("omnigroup: signal %s failed", sig)


def interrupt(proc: subprocess.Popen[Any] | None, run: Run = subprocess.run) -> None:
    """Ask the process (tree) to stop its current work: SIGINT. Windows has no such
    thing for a hidden child (CTRL_BREAK_EVENT is delivered per console, so it would
    reach the daemon itself or nobody): the tree is killed with `taskkill /T /F`."""
    if proc is None or proc.poll() is not None:
        return
    if is_windows():
        _taskkill(proc.pid, True, run)
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
    """The escalation after the first interrupt: terminate, then kill. On Windows a
    hidden child ignores `taskkill /T` without /F (no window to close), so go straight
    to the forced kill."""
    return (kill,) if is_windows() else (terminate, kill)


def install_stop_signals(stopping: threading.Event) -> None:
    """SIGTERM and, on Windows, SIGBREAK (CTRL_BREAK_EVENT) stop the daemon cleanly."""
    if threading.current_thread() is not threading.main_thread():
        return

    def request_stop(_signum: int, _frame: Any) -> None:
        stopping.set()

    for name in ("SIGTERM", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, request_stop)
