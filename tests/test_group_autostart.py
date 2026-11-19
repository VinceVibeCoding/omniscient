from pathlib import Path

import pytest

from omniscient.group.autostart import (
    MAX_COMMAND_CHARS,
    RUN_VALUE,
    Autostart,
    AutostartError,
)

PY = Path("C:/tools/omniscient/Scripts/python.exe")


class FakeRegistry:
    def __init__(
        self, values: dict[str, str] | None = None, fail: bool = False
    ) -> None:
        self.values = dict(values or {})
        self.fail = fail

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        if self.fail:
            raise AutostartError("écriture du registre refusée (test)")
        self.values[name] = value

    def delete(self, name: str) -> bool:
        return self.values.pop(name, None) is not None


def make(registry=None, platform="win32", windowless=True) -> Autostart:
    return Autostart(
        registry=registry if registry is not None else FakeRegistry(),
        platform=platform,
        interpreter=PY,
        exists=lambda _p: windowless,
    )


def test_install_writes_a_run_value_without_a_console() -> None:
    reg = FakeRegistry()
    assert make(reg).install(7341) == RUN_VALUE
    command = reg.values[RUN_VALUE]
    assert "pythonw.exe" in command
    assert command.endswith("-m omniscient group serve --port 7341")


def test_falls_back_to_console_python_without_pythonw() -> None:
    assert "pythonw" not in make(windowless=False).command(7341)


def test_refuses_off_windows_and_points_to_systemd() -> None:
    with pytest.raises(AutostartError, match="systemctl"):
        make(platform="linux").install(7341)


def test_a_refused_registry_write_is_reported() -> None:
    with pytest.raises(AutostartError, match="refusée"):
        make(FakeRegistry(fail=True)).install(7341)


def test_too_long_command_is_rejected() -> None:
    long = Autostart(
        registry=FakeRegistry(),
        interpreter=Path("C:/" + "a" * MAX_COMMAND_CHARS + "/python.exe"),
        platform="win32",
        exists=lambda _p: False,
    )
    with pytest.raises(AutostartError, match="trop long"):
        long.command(7341)


def test_remove_only_deletes_an_existing_value() -> None:
    assert make(FakeRegistry({RUN_VALUE: "x"})).remove() is True
    assert make(FakeRegistry()).remove() is False


def test_installed_reflects_the_run_value() -> None:
    assert make(FakeRegistry({RUN_VALUE: "x"})).installed() is True
    assert make(FakeRegistry()).installed() is False
