"""`omniscient group doctor`: injected fakes, no real machine, no secrets in the report."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from omniscient import cli
from omniscient.group import doctor as dr
from omniscient.group import portcheck as pc
from omniscient.group.doctor_win import WinFacts, real_facts

runner = CliRunner()
SECRET = "sk-ant-THIS-MUST-NEVER-APPEAR"
HOME = Path("/home/zoe-muller")


def _win_facts(**over: object) -> WinFacts:
    base: dict[str, object] = {
        "os_label": lambda: "Windows 11 (build 22631, édition Professional)",
        "architecture": lambda: "x64",
        "windows_build": lambda: 22631,
        "ui_language": lambda: "fr-FR",
        "ansi_codepage": lambda: 1252,
        "oem_codepage": lambda: 850,
        "powershell_version": lambda: "5.1.22621.4391",
        "webview2_version": lambda: "130.0.2849.80",
        "widget_version": lambda: "0.3.0",
        "widget_path": lambda: Path("C:/x/omnigroup.exe"),
    }
    return WinFacts(**{**base, **over})  # type: ignore[arg-type]


def _deps(**over: object) -> dr.DoctorDeps:
    base: dict[str, object] = {
        "platform": "win32",
        "environ": {},
        "home": Path("C:/Users/Zoé Müller (test)"),
        "run": lambda argv: (0, "uv 0.9.0\n"),
        "which": lambda name: "C:/pwsh.exe",
        "healthy": lambda port: True,
        "bind": lambda port: None,
        "engine_version": lambda: "0.3.0",
        "claude": lambda: "C:/Users/Zoé Müller (test)/.local/bin/claude.exe",
        "hook_events": lambda: (10, 10),
        "autostart": lambda: True,
        "disk_free": lambda path: 50 * dr.GIB,
        "win": _win_facts(),
    }
    return dr.DoctorDeps(**{**base, **over})  # type: ignore[arg-type]


def _by_label(lines: list[dr.Line]) -> dict[str, dr.Line]:
    return {line.label: line for line in lines}


def test_healthy_windows_machine_is_all_ok() -> None:
    lines = dr.run_checks(_deps())
    assert dr.exit_code(lines) == 0
    by = _by_label(lines)
    assert by["WebView2"].level == dr.OK and "130.0" in by["WebView2"].detail
    assert by["Démon"].level == dr.OK and by["Port"].level == dr.OK
    assert by["Hooks Claude Code"].detail == "10/10 événements"
    assert "fr-FR" in by["Langue et pages de code"].detail
    assert "ANSI 1252, OEM 850" in by["Langue et pages de code"].detail


def test_missing_webview2_hooks_and_daemon_are_ko_with_a_fix() -> None:
    lines = dr.run_checks(
        _deps(
            win=_win_facts(webview2_version=lambda: None),
            healthy=lambda port: False,
            hook_events=lambda: (0, 10),
            bind=lambda port: pc.PortProblem(port, pc.RESERVED),
        )
    )
    by = _by_label(lines)
    assert dr.exit_code(lines) == 1
    assert by["WebView2"].level == dr.KO and "EdgeWebView2Runtime" in by["WebView2"].fix
    assert (
        by["Hooks Claude Code"].level == dr.KO
        and "setup --write" in by["Hooks Claude Code"].fix
    )
    assert by["Démon"].level == dr.KO
    assert by["Port"].level == dr.KO and "--check-port" in by["Port"].fix


def test_free_port_with_daemon_down_is_ok_for_the_port() -> None:
    by = _by_label(dr.run_checks(_deps(healthy=lambda port: False)))
    assert by["Démon"].level == dr.KO and by["Port"].level == dr.OK


def test_widget_missing_is_info_with_the_antivirus_hint() -> None:
    win = _win_facts(widget_version=lambda: None, widget_path=lambda: None)
    line = _by_label(dr.run_checks(_deps(win=win)))["Widget Omnigroup"]
    assert (
        line.level == dr.INFO and "antivirus" in line.fix and "SmartScreen" in line.fix
    )


def test_arm64_and_old_windows_are_flagged() -> None:
    win = _win_facts(architecture=lambda: "ARM64", windows_build=lambda: 17000)
    texts = " ".join(
        f"{x.level} {x.label} {x.detail}" for x in dr.run_checks(_deps(win=win))
    )
    assert "ARM64" in texts and "Windows trop ancien" in texts


def test_a_check_that_raises_becomes_a_ko_line_and_others_still_run() -> None:
    def boom() -> str:
        raise RuntimeError("registry exploded")

    lines = dr.run_checks(_deps(win=_win_facts(webview2_version=boom)))
    by = _by_label(lines)
    assert by["webview"].level == dr.KO and "RuntimeError" in by["webview"].detail
    assert "Moteur" in by and "Espace disque" in by


def test_low_disk_space_is_ko() -> None:
    line = _by_label(dr.run_checks(_deps(disk_free=lambda p: 100 << 20)))[
        "Espace disque"
    ]
    assert line.level == dr.KO


def test_proxy_variables_are_named_never_valued() -> None:
    env = {
        "HTTPS_PROXY": f"http://user:{SECRET}@proxy.corp:8080",
        "no_proxy": "localhost",
    }
    deps = _deps(environ=env)
    text = "\n".join(dr.render(dr.run_checks(deps), deps))
    assert "HTTPS_PROXY" in text and "NO_PROXY" in text
    assert SECRET not in text and "proxy.corp" not in text and "user:" not in text


def test_profile_with_spaces_accents_and_parentheses_is_info_not_error() -> None:
    line = _by_label(dr.run_checks(_deps()))["Chemin du profil"]
    assert line.level == dr.INFO
    assert (
        "espaces" in line.detail
        and "non ASCII" in line.detail
        and "parenthèses" in line.detail
    )


def test_report_never_shows_the_user_name() -> None:
    deps = _deps()
    text = "\n".join(dr.render(dr.run_checks(deps), deps))
    assert "Zoé" not in text and "Müller" not in text
    assert "%USERPROFILE%/.local/bin/claude.exe" in text


def test_redact_forms_and_other_users_paths() -> None:
    home = Path("C:/Users/Zoé Müller (test)")
    raw = "a C:\\Users\\Zoé Müller (test)\\x b c:/users/zoé müller (test)/y d D:\\Users\\Other\\z"
    out = dr.redact(raw, home, windows=True)
    assert "Zoé" not in out and "Other" not in out
    assert "%USERPROFILE%" in out and "D:\\Users\\<utilisateur>" in out


def test_redact_wsl_home_and_windows_side_users() -> None:
    out = dr.redact(
        "/home/zoe-muller/.local and /mnt/c/Users/Bob/x", HOME, windows=False
    )
    assert "zoe-muller" not in out and "Bob" not in out
    assert out.startswith("~/.local")


def test_linux_skips_windows_checks() -> None:
    deps = _deps(platform="linux", wsl=True, home=HOME)
    labels = [x.label for x in dr.run_checks(deps)]
    assert "Système" in labels
    for windows_only in (
        "WebView2",
        "PowerShell",
        "Widget Omnigroup",
        "Démarrage automatique",
    ):
        assert windows_only not in labels


def test_report_has_summary_and_fix_arrows() -> None:
    deps = _deps(healthy=lambda port: False)
    out = dr.render(dr.run_checks(deps), deps)
    assert out[-1].startswith("Résumé : 1 problème")
    assert any(line.startswith("     -> omniscient group serve") for line in out)


@pytest.mark.skipif(
    sys.platform == "win32", reason="the real readers answer on Windows"
)
def test_real_facts_return_none_off_windows() -> None:
    facts = real_facts(lambda argv: (1, ""))
    assert facts.architecture() is None and facts.webview2_version() is None
    assert facts.ansi_codepage() is None and facts.widget_version() is None


def test_powershell_version_ignores_localized_text() -> None:
    from omniscient.group.doctor_win import powershell_version

    assert (
        powershell_version(lambda argv: (0, "Version : 5.1.22621.4391\n"))
        == "5.1.22621.4391"
    )
    assert powershell_version(lambda argv: (1, "erreur")) is None


def test_doctor_command_runs_and_exits_with_the_check_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = _deps(platform="linux", home=HOME, healthy=lambda port: True)
    monkeypatch.setattr(dr, "real_deps", lambda port: deps)
    result = runner.invoke(cli.app, ["group", "doctor"])
    assert result.exit_code == 0, result.output
    assert "Omniscient doctor" in result.output and "tout est OK" in result.output
