"""install.sh: syntax, shellcheck, and a real install into a throw-away HOME."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="install.sh targets Linux, macOS and WSL"
)


def test_script_parses_with_posix_sh() -> None:
    result = subprocess.run(
        ["sh", "-n", str(SCRIPT)], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_script_passes_shellcheck() -> None:
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    result = subprocess.run(
        ["shellcheck", "-s", "sh", str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_help_prints_usage_without_installing() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT), "--help"], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--wheel" in result.stdout


def test_rejects_unknown_option() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT), "--nope"], check=False, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "option inconnue" in result.stderr


def test_installs_engine_into_a_temporary_home(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    dist = tmp_path / "dist"
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)],
        check=False,
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        pytest.skip(f"cannot build the wheel (offline?): {build.stderr[-200:]}")
    wheel = next(dist.glob("*.whl"))
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("OMNISCIENT_")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"))
    env.pop("OMNISCIENT_HOME", None)
    result = subprocess.run(
        ["sh", str(SCRIPT), "--wheel", str(wheel), "--skip-widget", "--no-daemon"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    if result.returncode != 0 and "uv n'a pas pu installer" in result.stdout:
        pytest.skip("uv could not install dependencies (offline?)")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".local" / "bin" / "omniscient").exists()
    assert (home / ".claude" / "settings.json").exists()
