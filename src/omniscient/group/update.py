"""`omniscient update`: bring the engine and the widget to the latest published release.

The newest published `widget-v*` release carries the engine wheel, the widget installer,
`install.ps1` and `SHA256SUMS`. Every file is fetched over HTTPS (size-capped, redirects
only to GitHub hosts), checked against SHA256SUMS (plus the build provenance when `gh`
exists) and only then used. On Windows the running `omniscient.exe` and the widget are
locked, so the verified `install.ps1` runs in a detached PowerShell that waits for this
process to exit; elsewhere `uv tool install --force <wheel>` runs inline.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from omniscient.group import widget_release as wr

WHEEL = re.compile(r"^omniscient-([0-9][0-9A-Za-z.+!_]*)-py3-none-any\.whl$")
SETUP = re.compile(r"^Omniscient_([0-9][0-9A-Za-z.+_-]*)_x64-setup\.exe$")
SCRIPT_NAME = "install.ps1"
WHEEL_MAX = 32 * 1024 * 1024
SCRIPT_MAX = 256 * 1024
WIDGET_EXE_PARTS = (("Omniscient",), ("Programs", "Omniscient"))
DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS|NEW_GROUP|NO_WINDOW


class UpdateError(Exception):
    """The update cannot be found, verified or started."""


@dataclass(frozen=True)
class UpdatePlan:
    tag: str
    engine_installed: str
    engine_latest: str
    widget_installed: str | None  # None: no widget on this machine
    widget_latest: str
    wheel: wr.Asset
    installer: wr.Asset
    script: wr.Asset
    sums: wr.Asset

    @property
    def engine_outdated(self) -> bool:
        return version_key(self.engine_latest) > version_key(self.engine_installed)

    @property
    def widget_outdated(self) -> bool:
        have = self.widget_installed
        return have is not None and version_key(self.widget_latest) > version_key(have)

    @property
    def outdated(self) -> bool:
        return self.engine_outdated or self.widget_outdated


def version_key(text: str) -> tuple[int, ...]:
    """Numeric parts of a version (`0.2.1` -> (0, 2, 1)); suffixes are ignored."""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:4])


def installed_engine_version() -> str:
    try:
        return version("omniscient")
    except PackageNotFoundError:
        return "0"


def widget_exe(environ: dict[str, str] | None = None) -> Path | None:
    """The per-user Omniscient install (Windows), in either NSIS folder layout."""
    base = (environ or os.environ).get("LOCALAPPDATA")
    if not base:
        return None
    for parts in WIDGET_EXE_PARTS:
        candidate = Path(base, *parts, "omniscient-widget.exe")
        if candidate.is_file():
            return candidate
    return None


def installed_widget_version(
    runner: wr.Runner = wr._run, exe: Path | None = None, native: bool | None = None
) -> str | None:
    """ProductVersion of the installed widget exe, or None when it is not installed."""
    if not (sys.platform == "win32" if native is None else native):
        return None
    exe = exe or widget_exe()
    if exe is None:
        return None
    script = f"(Get-Item -LiteralPath '{_quote(str(exe))}').VersionInfo.ProductVersion"
    code, out = runner(["powershell.exe", "-NoProfile", "-Command", script])
    found = re.search(r"\d+(\.\d+)+", out) if code == 0 else None
    return found.group(0) if found else "0"


def _quote(text: str) -> str:
    return text.replace("'", "''")


def plan_update(
    fetch: wr.Fetch = wr.https_fetch,
    engine_version: Callable[[], str] = installed_engine_version,
    widget_version: Callable[[], str | None] = installed_widget_version,
) -> UpdatePlan:
    """What is installed against the newest release that carries all four assets."""
    for tag, assets in wr.published_releases(fetch):
        wheel = wr.find_asset(assets, tag, lambda n: bool(WHEEL.match(n)))
        installer = wr.find_asset(assets, tag, lambda n: bool(SETUP.match(n)))
        script = wr.find_asset(assets, tag, lambda n: n == SCRIPT_NAME)
        sums = wr.find_asset(assets, tag, lambda n: n == wr.SUMS_NAME)
        if wheel and installer and script and sums:
            engine, widget = WHEEL.match(wheel.name), SETUP.match(installer.name)
            assert engine and widget
            return UpdatePlan(
                tag, engine_version(), engine.group(1), widget_version(),
                widget.group(1), wheel, installer, script, sums,
            )  # fmt: skip
    raise UpdateError(
        "aucune version publiée ne contient le moteur, le widget et install.ps1 : "
        "mise à jour impossible pour l'instant."
    )


def fetch_verified(
    asset: wr.Asset,
    sums_text: str,
    dest: Path,
    max_bytes: int,
    fetch: wr.Fetch,
    attest: wr.Attest,
) -> Path:
    """Download `asset` into `dest`; it gets its name only after SHA-256 and `attest`."""
    import hashlib

    want = wr.expected_sha(sums_text, asset.name)
    data = fetch(asset.url, max_bytes)
    if hashlib.sha256(data).hexdigest() != want:
        raise wr.ReleaseError(f"SHA256 différent pour {asset.name} : fichier rejeté")
    dest.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest, prefix=".update-", suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        attest(tmp)
        target = dest / asset.name
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def download_all(
    plan: UpdatePlan, dest: Path, fetch: wr.Fetch, attest: wr.Attest
) -> dict[str, Path]:
    """The verified wheel, install.ps1 and (when the widget is to be updated) installer."""
    sums = fetch(plan.sums.url, wr.SUMS_MAX).decode("utf-8", errors="replace")
    files = {
        "wheel": fetch_verified(plan.wheel, sums, dest, WHEEL_MAX, fetch, attest),
        "script": fetch_verified(plan.script, sums, dest, SCRIPT_MAX, fetch, attest),
    }
    if plan.widget_outdated:
        files["installer"] = fetch_verified(
            plan.installer, sums, dest, wr.INSTALLER_MAX, fetch, attest
        )
    return files


def detached_command(
    files: dict[str, Path], log: Path, parent_pid: int, app: Path | None
) -> list[str]:
    """argv of the hidden PowerShell: wait for us, run the verified install.ps1, clean up."""
    script, wheel = _quote(str(files["script"])), _quote(str(files["wheel"]))
    args = f"-Wheel '{wheel}'"
    args += (
        f" -Installer '{_quote(str(files['installer']))}'"
        if "installer" in files
        else " -SkipWidget"
    )
    restart = f"; Start-Process -FilePath '{_quote(str(app))}'" if app else ""
    body = (
        f"Wait-Process -Id {parent_pid} -ErrorAction SilentlyContinue; "
        f"& ([scriptblock]::Create([IO.File]::ReadAllText('{script}', "
        f"[Text.Encoding]::UTF8))) {args} *>&1 | Out-File -LiteralPath "
        f"'{_quote(str(log))}' -Encoding utf8{restart}"
    )
    return [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "ByPass",
        "-WindowStyle", "Hidden", "-Command", body,
    ]  # fmt: skip


def spawn_detached(argv: list[str]) -> None:
    subprocess.Popen(  # argv list, no shell; survives this process
        argv,
        creationflags=DETACHED,  # type: ignore[call-overload,unused-ignore]
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
