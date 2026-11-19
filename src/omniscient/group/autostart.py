"""Start the omnigroup daemon at Windows logon: a per-user `Run` registry value.

`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run` is writable by any user, never
asks for administrator rights and works on every Windows edition (a scheduled task
created with `schtasks /SC ONLOGON` is refused on many PCs without elevation). The value
launches the daemon with `pythonw.exe -m omniscient group serve` (no console window) when
that interpreter exists, else with the console `python.exe`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Omnigroup"
MAX_COMMAND_CHARS = 260  # Windows reads at most MAX_PATH characters of a Run command


class AutostartError(Exception):
    """Autostart cannot be set up here (not Windows, registry refused, command too long)."""


class RunRegistry(Protocol):
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...


class WindowsRunRegistry:
    """The current user's Run key, through the standard-library `winreg`."""

    def _open(self, access: int):
        import winreg  # Windows only: imported here so other platforms can load this module

        return winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)

    def get(self, name: str) -> str | None:
        import winreg

        try:
            with self._open(winreg.KEY_READ) as key:
                value, _kind = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AutostartError(f"lecture du registre refusée ({exc})") from exc
        return str(value)

    def set(self, name: str, value: str) -> None:
        import winreg

        try:
            with self._open(winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        except OSError as exc:
            raise AutostartError(f"écriture du registre refusée ({exc})") from exc

    def delete(self, name: str) -> bool:
        import winreg

        try:
            with self._open(winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise AutostartError(
                f"suppression dans le registre refusée ({exc})"
            ) from exc
        return True


@dataclass(frozen=True)
class Autostart:
    registry: RunRegistry = field(default_factory=WindowsRunRegistry)
    platform: str = sys.platform
    interpreter: Path = Path(sys.executable)
    exists: Callable[[Path], bool] = Path.exists

    def _require_windows(self) -> None:
        if self.platform != "win32":
            raise AutostartError(
                "le démarrage automatique par la clé Run ne marche que sous "
                "Windows ; sous WSL/Linux : `omniscient schedule install`, puis "
                "`systemctl --user enable --now omnigroup`."
            )

    def command(self, port: int) -> str:
        """The Run value: quoted interpreter, then the daemon arguments."""
        windowless = self.interpreter.with_name("pythonw.exe")
        python = windowless if self.exists(windowless) else self.interpreter
        text = f'"{python}" -m omniscient group serve --port {port}'
        if len(text) > MAX_COMMAND_CHARS:
            raise AutostartError(
                f"chemin trop long pour le démarrage automatique ({len(text)} caractères)"
            )
        return text

    def install(self, port: int) -> str:
        self._require_windows()
        self.registry.set(RUN_VALUE, self.command(port))
        return RUN_VALUE

    def remove(self) -> bool:
        """True when the value was removed, False when there was none."""
        self._require_windows()
        return self.registry.delete(RUN_VALUE)

    def installed(self) -> bool:
        self._require_windows()
        return self.registry.get(RUN_VALUE) is not None
