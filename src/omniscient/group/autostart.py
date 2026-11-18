"""Start the omnigroup daemon at Windows logon: a per-user scheduled task.

`schtasks /Create /SC ONLOGON` without /RU runs the task as the current user, at the
limited run level: no administrator rights, nothing machine-wide. The task launches the
daemon with `pythonw.exe -m omniscient group serve` (no console window) when that
interpreter exists, else with the console `python.exe`. Commands are argv lists, never a
shell string.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from omniscient.group.actions import Runner, default_runner

TASK_NAME = "Omnigroup"
MAX_COMMAND_CHARS = 261  # schtasks refuses a /TR longer than this


class AutostartError(Exception):
    """Autostart cannot be set up here (not Windows, task refused, command too long)."""


@dataclass(frozen=True)
class Autostart:
    runner: Runner = default_runner
    platform: str = sys.platform
    interpreter: Path = Path(sys.executable)
    exists: Callable[[Path], bool] = Path.exists

    def _require_windows(self) -> None:
        if self.platform != "win32":
            raise AutostartError(
                "le démarrage automatique par tâche planifiée ne marche que sous "
                "Windows ; sous WSL/Linux : `omniscient schedule install`, puis "
                "`systemctl --user enable --now omnigroup`."
            )

    def command(self, port: int) -> str:
        """The `/TR` value: quoted interpreter, then the daemon arguments."""
        windowless = self.interpreter.with_name("pythonw.exe")
        python = windowless if self.exists(windowless) else self.interpreter
        text = f'"{python}" -m omniscient group serve --port {port}'
        if len(text) > MAX_COMMAND_CHARS:
            raise AutostartError(
                f"chemin trop long pour une tâche planifiée ({len(text)} caractères)"
            )
        return text

    def install(self, port: int) -> str:
        self._require_windows()
        argv = [
            "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
            "/TR", self.command(port), "/RL", "LIMITED", "/F",
        ]  # fmt: skip
        self._run(argv, "création de la tâche")
        return TASK_NAME

    def remove(self) -> bool:
        """True when a task was removed, False when there was none."""
        self._require_windows()
        if not self.installed():
            return False
        self._run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], "suppression")
        return True

    def installed(self) -> bool:
        self._require_windows()
        code, _ = self.runner(["schtasks", "/Query", "/TN", TASK_NAME])
        return code == 0

    def _run(self, argv: Sequence[str], what: str) -> None:
        code, out = self.runner(argv)
        if code != 0:
            detail = out.strip().splitlines()[-1] if out.strip() else f"code {code}"
            raise AutostartError(f"schtasks : échec de la {what} ({detail})")
