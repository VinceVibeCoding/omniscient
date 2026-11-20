"""install.ps1 cannot run here (Linux): static guarantees about what it may do."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "install.ps1").read_text(encoding="utf-8")
CODE = "\n".join(
    line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#")
)


def test_documented_parameters_exist() -> None:
    head = SCRIPT.split("function ", 1)[0]
    for name in (
        "$Wheel",
        "$Installer",
        "$SkipWidget",
        "$NoAutostart",
        "$NoLaunch",
        "$Port",
    ):
        assert name in head


def test_only_the_uv_fallback_is_piped_to_iex() -> None:
    hits = [m.group(0) for m in re.finditer(r"(?i)\|\s*iex|Invoke-Expression", CODE)]
    assert len(hits) == 1
    assert "astral.sh/uv/install.ps1" in CODE


def test_needs_no_admin_and_no_git() -> None:
    assert not re.search(r"(?i)-Verb\s+RunAs|git\+https|\bgit\s+clone", CODE)
    assert "Set-ExecutionPolicy" not in CODE


def test_checks_the_wheel_hash_before_installing() -> None:
    assert CODE.index("Get-FileHash") < CODE.index("'tool', 'install'")
    assert "SHA256SUMS" in CODE


def test_no_personal_data() -> None:
    assert not re.search(r"(?i)/home/|C:\\Users\\|@[a-z0-9-]+\.(com|fr)", SCRIPT)


def test_checks_the_port_before_starting_the_hidden_daemon() -> None:
    assert CODE.index("'--check-port'") < CODE.index("Start-Process -FilePath $omni")


def test_failure_points_to_doctor() -> None:
    assert "omniscient group doctor" in CODE


def test_children_speak_utf8_and_the_environment_is_restored() -> None:
    assert "PYTHONIOENCODING = 'utf-8'" in CODE
    assert "$env:PYTHONUTF8 = $savedEnv.PYTHONUTF8" in CODE


def test_every_parameter_has_an_environment_variable_for_the_iex_path() -> None:
    head = SCRIPT.split("param(", 1)[0]
    for name in ("WHEEL", "INSTALLER", "SKIPWIDGET", "NOAUTOSTART", "NOLAUNCH", "PORT"):
        assert f"OMNISCIENT_INSTALL_{name}" in head
        assert f"'{name}'" in CODE


def test_launches_the_installed_widget_unless_no_launch() -> None:
    assert "Start-Process -FilePath $app" in CODE
    assert "-not $NoLaunch" in CODE


def test_final_text_is_short_and_has_no_manual_pairing_steps() -> None:
    assert "saisis les 6 chiffres affichés sur ton bureau" in CODE
    assert "Demander un code" not in CODE
