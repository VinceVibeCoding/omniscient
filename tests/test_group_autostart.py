from pathlib import Path

import pytest

from omniscient.group.autostart import MAX_COMMAND_CHARS, Autostart, AutostartError

PY = Path("C:/tools/omniscient/Scripts/python.exe")


def make(calls, platform="win32", code=0, out="", windowless=True):
    def runner(argv):
        calls.append(list(argv))
        return code, out

    return Autostart(
        runner=runner, platform=platform, interpreter=PY, exists=lambda _p: windowless
    )


def test_install_creates_a_limited_logon_task_without_a_console() -> None:
    calls: list[list[str]] = []
    make(calls).install(7341)
    argv = calls[0]
    assert argv[:2] == ["schtasks", "/Create"]
    assert argv[argv.index("/SC") + 1] == "ONLOGON"
    assert argv[argv.index("/RL") + 1] == "LIMITED"
    assert "/RU" not in argv  # current user, never SYSTEM
    tr = argv[argv.index("/TR") + 1]
    assert "pythonw.exe" in tr and tr.endswith("-m omniscient group serve --port 7341")


def test_falls_back_to_console_python_without_pythonw() -> None:
    assert "pythonw" not in make([], windowless=False).command(7341)


def test_refuses_off_windows_and_points_to_systemd() -> None:
    with pytest.raises(AutostartError, match="systemctl"):
        make([], platform="linux").install(7341)


def test_a_refused_task_reports_schtasks_message() -> None:
    with pytest.raises(AutostartError, match="Accès refusé"):
        make([], code=1, out="ERREUR : Accès refusé\n").install(7341)


def test_too_long_command_is_rejected() -> None:
    long = Autostart(
        interpreter=Path("C:/" + "a" * MAX_COMMAND_CHARS + "/python.exe"),
        platform="win32",
        exists=lambda _p: False,
    )
    with pytest.raises(AutostartError, match="trop long"):
        long.command(7341)


def test_remove_only_deletes_an_existing_task() -> None:
    calls: list[list[str]] = []
    assert make(calls).remove() is True
    assert [c[1] for c in calls] == ["/Query", "/Delete"]
    gone: list[list[str]] = []
    assert make(gone, code=1).remove() is False
    assert [c[1] for c in gone] == ["/Query"]
