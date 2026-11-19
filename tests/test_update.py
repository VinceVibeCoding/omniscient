"""`omniscient update`: release planning, verified downloads, apply paths (no network)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from omniscient import cli_update
from omniscient.group import update as up
from omniscient.group import widget_release as wr

TAG = "widget-v0.3.0"
BASE = f"https://github.com/{wr.REPO}/releases/download/{TAG}"
FILES = {
    "omniscient-0.3.0-py3-none-any.whl": b"wheel",
    "Omnigroup_0.3.0_x64-setup.exe": b"MZ exe",
    "install.ps1": b"# script",
}


def listing(skip: str | None = None) -> list[dict]:
    names = [*FILES, "SHA256SUMS"]
    assets = [
        {"name": n, "browser_download_url": f"{BASE}/{n}"} for n in names if n != skip
    ]
    return [{"tag_name": TAG, "draft": False, "prerelease": False, "assets": assets}]


def fake_fetch(skip: str | None = None, tamper: str | None = None) -> Any:
    sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in FILES.items())

    def fetch(url: str, max_bytes: int) -> bytes:
        if "api.github.com" in url:
            return json.dumps(listing(skip)).encode()
        name = url.rsplit("/", 1)[-1]
        if name == "SHA256SUMS":
            return sums.encode()
        return b"tampered" if name == tamper else FILES[name]

    return fetch


def plan(
    engine: str = "0.2.0", widget: str | None = "0.2.0", **kw: Any
) -> up.UpdatePlan:
    return up.plan_update(fake_fetch(**kw), lambda: engine, lambda: widget)


class Say:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def deps(tmp_path: Path, say: Say, **kw: Any) -> cli_update.UpdateDeps:
    base: dict[str, Any] = {
        "say": say,
        "fetch": fake_fetch(),
        "attest": lambda p: "unavailable",
        "plan": lambda: plan(),
        "temp_dir": lambda: tmp_path / "dl",
        "native_windows": False,
        "pid": 4242,
    }
    base.update(kw)
    return cli_update.UpdateDeps(**base)


def test_version_comparison_is_numeric() -> None:
    assert up.version_key("0.10.0") > up.version_key("0.9.9")
    assert plan("0.3.0", "0.3.0").outdated is False
    assert (
        plan("0.3.0", "0.2.0").widget_outdated
        and not plan("0.3.0", "0.2.0").engine_outdated
    )
    assert plan("0.2.0", None).outdated and plan("0.2.0", None).widget_installed is None


def test_a_release_missing_an_asset_is_not_an_update() -> None:
    with pytest.raises(up.UpdateError):
        plan(skip="install.ps1")


def test_check_changes_nothing_and_signals_with_the_exit_code(tmp_path: Path) -> None:
    say = Say()
    assert cli_update.run_update(True, False, deps(tmp_path, say)) == 1
    assert not (tmp_path / "dl").exists()
    ok = deps(tmp_path, Say(), plan=lambda: plan("0.3.0", "0.3.0"))
    assert cli_update.run_update(True, False, ok) == 0


def test_up_to_date_stops(tmp_path: Path) -> None:
    say = Say()
    d = deps(tmp_path, say, plan=lambda: plan("0.3.0", None))
    assert cli_update.run_update(False, False, d) == 0
    assert "déjà à jour" in say.text and not (tmp_path / "dl").exists()


def test_dry_run_downloads_nothing(tmp_path: Path) -> None:
    say = Say()
    assert cli_update.run_update(False, True, deps(tmp_path, say)) == 0
    assert "--dry-run" in say.text and not (tmp_path / "dl").exists()


def test_tampered_file_is_rejected(tmp_path: Path) -> None:
    say = Say()
    d = deps(tmp_path, say, fetch=fake_fetch(tamper="install.ps1"))
    assert cli_update.run_update(False, False, d) == 2
    assert "SHA256 différent" in say.text
    assert not (tmp_path / "dl" / "install.ps1").exists()


def test_windows_apply_spawns_the_detached_installer(tmp_path: Path) -> None:
    say, spawned = Say(), []
    exe = tmp_path / "omnigroup.exe"
    d = deps(
        tmp_path,
        say,
        native_windows=True,
        spawn=spawned.append,
        widget_path=lambda: exe,
    )
    assert cli_update.run_update(False, False, d) == 0
    argv = spawned[0]
    assert argv[0] == "powershell.exe" and "-Command" in argv and "Hidden" in argv
    body = argv[-1]
    assert "Wait-Process -Id 4242" in body
    assert "install.ps1" in body and "-Wheel" in body and "-Installer" in body
    assert "omnigroup.exe" in body
    assert "en arrière-plan" in say.text and "update.log" in say.text
    assert (tmp_path / "dl" / "install.ps1").read_bytes() == FILES["install.ps1"]


def test_windows_without_widget_update_skips_the_installer(tmp_path: Path) -> None:
    spawned: list[list[str]] = []
    d = deps(
        tmp_path, Say(), native_windows=True, spawn=spawned.append,
        plan=lambda: plan("0.2.0", None),
    )  # fmt: skip
    assert cli_update.run_update(False, False, d) == 0
    assert "-SkipWidget" in spawned[0][-1] and "-Installer" not in spawned[0][-1]
    assert not (tmp_path / "dl" / "Omnigroup_0.3.0_x64-setup.exe").exists()


def test_quotes_in_paths_are_escaped() -> None:
    argv = up.detached_command(
        {"script": Path("C:/o'brien/install.ps1"), "wheel": Path("w.whl")},
        Path("log.txt"), 1, None,
    )  # fmt: skip
    assert "o''brien" in argv[-1]


def test_linux_runs_uv_inline(tmp_path: Path) -> None:
    say, calls = Say(), []

    def run(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        return 0, ""

    d = deps(tmp_path, say, run=run, which=lambda n: "/usr/bin/uv")
    assert cli_update.run_update(False, False, d) == 0
    assert calls[0][1:4] == ["tool", "install", "--force"]
    assert calls[0][4].endswith("omniscient-0.3.0-py3-none-any.whl")
    assert "Redémarre le démon" in say.text


def test_linux_without_uv_is_explained(tmp_path: Path) -> None:
    say = Say()
    d = deps(tmp_path, say, which=lambda n: None)
    assert cli_update.run_update(False, False, d) == 2
    assert "uv" in say.text


def test_widget_version_is_read_through_the_runner(tmp_path: Path) -> None:
    exe = tmp_path / "omnigroup.exe"
    got = up.installed_widget_version(lambda argv: (0, "0.2.0\r\n"), exe, native=True)
    assert got == "0.2.0"
    assert up.installed_widget_version(lambda a: (0, ""), exe, native=False) is None


def test_widget_exe_layouts(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path)}
    assert up.widget_exe(env) is None
    target = tmp_path / "Programs" / "Omnigroup" / "omnigroup.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    assert up.widget_exe(env) == target
