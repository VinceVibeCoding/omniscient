"""Can the daemon listen on its port? A bind test and a French explanation of a "no".

Two ways to lose on Windows, both silent until the daemon dies: another program already
listens there (WinError 10048), or Windows reserved the port (WinError 10013: Hyper-V,
WSL, Docker or winnat keep "excluded port ranges"). The probe binds like the daemon does
(`GroupServer.server_bind`): no SO_REUSEADDR on Windows, where it would let a second
process share a busy port, and SO_REUSEADDR elsewhere. Never parse netsh or netstat
output (it is localized): the exit status of `bind` is the language-independent answer.
"""

from __future__ import annotations

import errno
import os
import socket
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_PORT = 7341
URL_ENV = "OMNIGROUP_URL"
BIND_HOST = "127.0.0.1"
WSAEADDRINUSE = 10048
WSAEACCES = 10013
SUGGESTION_SPAN = 10  # ports tried after the given one when suggesting another
MAX_PORT = 65535

BUSY, RESERVED, INVALID, OTHER = "busy", "reserved", "invalid", "other"
Binder = Callable[[int, bool], None]


@dataclass(frozen=True)
class PortProblem:
    port: int
    kind: str  # BUSY | RESERVED | INVALID | OTHER
    detail: str = ""


def configured_port(environ: Mapping[str, str] | None = None) -> int:
    """The port of OMNIGROUP_URL (the address hooks use), else the default 7341."""
    url = (os.environ if environ is None else environ).get(URL_ENV, "")
    try:
        port = urlsplit(url).port if url else None
    except ValueError:
        port = None
    return port if port and 0 < port <= MAX_PORT else DEFAULT_PORT


def _bind_once(port: int, windows: bool) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if not windows and hasattr(socket, "SO_REUSEADDR"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((BIND_HOST, port))
    finally:
        sock.close()


def probe_bind(
    port: int, windows: bool | None = None, bind: Binder = _bind_once
) -> PortProblem | None:
    """None when 127.0.0.1:`port` can be bound now, else why not."""
    if not 0 < port <= MAX_PORT:
        return PortProblem(port, INVALID, f"{port} n'est pas entre 1 et {MAX_PORT}")
    win = sys.platform == "win32" if windows is None else windows
    try:
        bind(port, win)
    except OSError as exc:
        return PortProblem(port, _kind(exc), str(exc))
    return None


def _kind(exc: OSError) -> str:
    code = getattr(exc, "winerror", None) or exc.errno
    if code in (WSAEADDRINUSE, errno.EADDRINUSE):
        return BUSY
    if code in (WSAEACCES, errno.EACCES):
        return RESERVED
    return OTHER


def suggest_port(
    start: int, windows: bool | None = None, bind: Binder = _bind_once
) -> int | None:
    """The first free port after `start` (a handful of tries), or None."""
    for port in range(start + 1, min(start + 1 + SUGGESTION_SPAN, MAX_PORT + 1)):
        if probe_bind(port, windows, bind) is None:
            return port
    return None


def fix_steps(other: int) -> list[str]:
    """What must change together for the daemon to live on port `other`."""
    url = f"http://127.0.0.1:{other}"
    setenv = f"[Environment]::SetEnvironmentVariable('OMNIGROUP_URL','{url}','User')"
    return [
        f"1. Lance le démon sur un autre port : omniscient group serve --port {other}",
        "2. Démarrage à l'ouverture de session : "
        + f"omniscient group autostart install --write --port {other}",
        f"3. Widget : Réglages, champ « Adresse du démon » : {url}",
        f"4. Hooks de Claude Code : variable utilisateur OMNIGROUP_URL = {url}, puis "
        + f"rouvre Claude Code. PowerShell : {setenv}",
        "   (ensuite `omniscient group status`, `pair` et `serve` prennent ce port seuls.)",
    ]


def explain(problem: PortProblem, other: int | None) -> str:
    """The French message: which port, why, and exactly how to fix it."""
    port = problem.port
    if problem.kind == INVALID:
        return f"Port invalide : {problem.detail}."
    why = {
        BUSY: f"Le port {port} est déjà occupé par un autre programme (ou une autre "
        "session Windows). Ferme ce programme, ou utilise un autre port.",
        RESERVED: f"Le port {port} est indisponible : Windows l'a réservé (plage exclue "
        "par Hyper-V, WSL, Docker ou une mise à jour). Pour voir les plages réservées : "
        "netsh interface ipv4 show excludedportrange protocol=tcp",
    }.get(problem.kind, f"Le port {port} est inutilisable ({problem.detail}).")
    if other is None:
        return why + f"\nChoisis un port libre avec --port (ex. {port + 1})."
    steps = "\n  ".join(fix_steps(other))
    return why + f"\nPour corriger, change de port (ici {other}) :\n  " + steps


@dataclass(frozen=True)
class Preflight:
    message: str  # empty: nothing to say, go ahead
    blocked: bool = False
    already_running: bool = False


def preflight(
    port: int,
    healthy: Callable[[int], bool],
    windows: bool | None = None,
    bind: Binder = _bind_once,
) -> Preflight:
    """Before `serve`: free port -> go; our daemon already there -> say so; else explain."""
    problem = probe_bind(port, windows, bind)
    if problem is None:
        return Preflight(f"Port {port} libre.")
    if problem.kind == BUSY and healthy(port):
        return Preflight(
            f"omnigroup tourne déjà sur http://{BIND_HOST}:{port} : rien à relancer.",
            already_running=True,
        )
    other = suggest_port(port, windows, bind) if problem.kind != INVALID else None
    return Preflight(explain(problem, other), blocked=True)
