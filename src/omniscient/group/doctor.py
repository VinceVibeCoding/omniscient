"""`omniscient group doctor`: a read-only health report that is safe to paste in a bug report.

Every line is OK, KO or INFO, with a fix hint on the KO ones. Nothing secret is read or
printed (no token, key or file content), user names in paths become `%USERPROFILE%`
(`~` on Linux), and proxy variables only say whether they are set. A check that raises
becomes a KO line, never a traceback. Windows-only checks come from `WinFacts`
(doctor_win.py: kernel32 and the registry, never localized tool output); on Linux/WSL
they are skipped.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from omniscient.group import portcheck
from omniscient.group.actions import Runner, default_runner, is_wsl
from omniscient.group.doctor_win import WinFacts, real_facts

OK, KO, INFO = "OK", "KO", "INFO"
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
MIN_FREE_BYTES = 1 << 30  # uv's Python + the engine's venv need about half a GiB
LONG_PROFILE = 80  # characters: classic MAX_PATH trouble starts with deep trees
GIB = 1 << 30
PLAIN_PATH = re.compile(r"^[A-Za-z0-9_.:\\/-]+$")
USERS_DIR = re.compile(
    r"(?i)((?:[a-z]:|/mnt/[a-z]|)[\\/]+(?:users|home)[\\/]+)[^\\/\s'\"]+"
)


@dataclass(frozen=True)
class Line:
    level: str  # OK | KO | INFO
    label: str
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class DoctorDeps:
    """Everything the checks read from the machine; tests pass fakes."""

    platform: str = sys.platform
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    home: Path = field(default_factory=Path.home)
    run: Runner = default_runner
    which: Callable[[str], str | None] = shutil.which
    port: int = portcheck.DEFAULT_PORT
    healthy: Callable[[int], bool] = lambda port: False
    bind: Callable[[int], portcheck.PortProblem | None] = portcheck.probe_bind
    engine_version: Callable[[], str | None] = lambda: None
    python_version: str = sys.version.split()[0]
    claude: Callable[[], str | None] = lambda: None
    hook_events: Callable[[], tuple[int, int]] = lambda: (0, 0)  # (installed, wanted)
    autostart: Callable[[], bool] = lambda: False
    disk_free: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free
    wsl: bool = False
    win: WinFacts = field(default_factory=WinFacts)

    @property
    def windows(self) -> bool:
        return self.platform == "win32"


def redact(text: str, home: Path, windows: bool) -> str:
    """Hide the user's name: the profile folder, then any other `Users\\<name>` path."""
    placeholder = "%USERPROFILE%" if windows else "~"
    out = text
    for form in {str(home), home.as_posix(), str(home).replace("\\", "\\\\")}:
        if form and len(form) > 3:
            out = re.sub(
                re.escape(form), lambda _: placeholder, out, flags=re.IGNORECASE
            )
    return USERS_DIR.sub(lambda m: m.group(1) + "<utilisateur>", out)


# ---- checks ------------------------------------------------------------------------------


def check_system(d: DoctorDeps) -> list[Line]:
    if not d.windows:
        where = "WSL" if d.wsl else "Linux/macOS"
        return [
            Line(INFO, "Système", f"{where} ({d.platform}) : contrôles Windows ignorés")
        ]
    label, arch, build = d.win.os_label(), d.win.architecture(), d.win.windows_build()
    lines = [Line(INFO, "Windows", f"{label or '?'}, architecture {arch or '?'}")]
    if build is not None and build < 17763:
        lines.append(
            Line(
                KO,
                "Windows trop ancien",
                f"build {build}",
                "Windows 10 1809 ou plus récent",
            )
        )
    if arch == "ARM64":
        lines.append(
            Line(
                INFO,
                "ARM64",
                "le widget est x64 : il tourne en émulation (Windows 11 requis)",
            )
        )
    return lines


def check_locale(d: DoctorDeps) -> list[Line]:
    if not d.windows:
        return []
    ansi, oem, ui = d.win.ansi_codepage(), d.win.oem_codepage(), d.win.ui_language()
    note = "" if ansi == 65001 else " (normal : Omniscient lit et écrit en UTF-8)"
    return [
        Line(
            INFO,
            "Langue et pages de code",
            f"affichage {ui or '?'}, ANSI {ansi}, OEM {oem}{note}",
        )
    ]


def check_powershell(d: DoctorDeps) -> list[Line]:
    if not d.windows:
        return []
    found = d.win.powershell_version()
    if found is None:
        return [
            Line(
                KO,
                "PowerShell",
                "introuvable",
                "Windows PowerShell 5.1 est fourni avec Windows",
            )
        ]
    pwsh = "présent" if d.which("pwsh") else "absent"
    return [Line(OK, "PowerShell", f"Windows PowerShell {found} ; PowerShell 7 {pwsh}")]


def check_webview(d: DoctorDeps) -> list[Line]:
    if not d.windows:
        return []
    found = d.win.webview2_version()
    if found:
        return [Line(OK, "WebView2", f"runtime {found}")]
    return [
        Line(
            KO, "WebView2", "runtime absent (le widget ne s'affichera pas)",
            "winget install Microsoft.EdgeWebView2Runtime (ou le télécharger sur microsoft.com)",
        )
    ]  # fmt: skip


def check_tools(d: DoctorDeps) -> list[Line]:
    code, out = d.run(["uv", "--version"])
    uv = out.strip().splitlines()[0] if code == 0 and out.strip() else None
    engine = d.engine_version()
    return [
        Line(OK, "uv", uv) if uv else Line(KO, "uv", "introuvable", "relance install.ps1 (il installe uv)"),
        Line(INFO, "Python", f"{d.python_version} (celui du moteur)"),
        Line(OK, "Moteur", f"omniscient {engine}")
        if engine
        else Line(KO, "Moteur", "version illisible", "réinstalle : uv tool install --force <roue>"),
    ]  # fmt: skip


def check_widget(d: DoctorDeps) -> list[Line]:
    if not d.windows:
        return []
    found, path = d.win.widget_version(), d.win.widget_path()
    if found or path:
        return [Line(OK, "Widget Omnigroup", f"installé (version {found or '?'})")]
    return [
        Line(
            INFO, "Widget Omnigroup", "non installé (omnigroup.exe introuvable)",
            "si l'installation vient d'avoir lieu : un antivirus ou SmartScreen l'a peut-être "
            "bloqué ; ajoute une exception pour %LOCALAPPDATA%\\Omnigroup puis relance install.ps1",
        )
    ]  # fmt: skip


def check_daemon(d: DoctorDeps) -> list[Line]:
    url = f"http://127.0.0.1:{d.port}"
    if d.healthy(d.port):
        return [
            Line(OK, "Démon", f"répond sur {url}"),
            Line(OK, "Port", f"{d.port} tenu par le démon omnigroup (normal)"),
        ]
    lines = [Line(KO, "Démon", f"ne répond pas sur {url}", "omniscient group serve")]
    problem = d.bind(d.port)
    if problem is None:
        lines.append(Line(OK, "Port", f"{d.port} libre (test d'ouverture réussi)"))
        return lines
    steps = (
        f"omniscient group serve --check-port, puis un autre --port (ex. {d.port + 1})"
    )
    lines.append(Line(KO, "Port", f"{d.port} inutilisable ({problem.kind})", steps))
    return lines


def check_claude(d: DoctorDeps) -> list[Line]:
    found = d.claude()
    if found:
        return [Line(OK, "Claude Code", f"trouvé : {found}")]
    return [Line(INFO, "Claude Code", "introuvable (facultatif : conversations de code)",
                 "irm https://claude.ai/install.ps1 | iex")]  # fmt: skip


def check_hooks(d: DoctorDeps) -> list[Line]:
    have, wanted = d.hook_events()
    if wanted and have == wanted:
        return [Line(OK, "Hooks Claude Code", f"{have}/{wanted} événements")]
    return [Line(KO, "Hooks Claude Code", f"{have}/{wanted} événements",
                 "omniscient group setup --write")]  # fmt: skip


def check_autostart(d: DoctorDeps) -> list[Line]:
    if not d.windows:
        return []
    if d.autostart():
        return [Line(OK, "Démarrage automatique", "tâche planifiée Omnigroup présente")]
    return [Line(INFO, "Démarrage automatique", "absent",
                 "omniscient group autostart install --write")]  # fmt: skip


def check_environment(d: DoctorDeps) -> list[Line]:
    names = {k.upper() for k in d.environ if d.environ[k]}
    set_vars = [v for v in PROXY_VARS if v in names]
    proxy = (
        f"variables définies : {', '.join(set_vars)} (valeurs non affichées)"
        if set_vars
        else "aucune"
    )
    lines = [Line(INFO, "Proxy", proxy)]
    url = d.environ.get(portcheck.URL_ENV)
    if url:
        lines.append(
            Line(
                INFO,
                "OMNIGROUP_URL",
                f"définie, port {portcheck.configured_port(d.environ)}",
            )
        )
    return lines


def check_disk(d: DoctorDeps) -> list[Line]:
    free = d.disk_free(d.home)
    text = f"{free / GIB:.1f} Gio libres sur le disque du profil"
    if free < MIN_FREE_BYTES:
        return [Line(KO, "Espace disque", text, "libère au moins 1 Gio")]
    return [Line(OK, "Espace disque", text)]


def check_profile(d: DoctorDeps) -> list[Line]:
    raw = str(d.home)
    traits = []
    if " " in raw:
        traits.append("espaces")
    if not raw.isascii():
        traits.append("caractères non ASCII")
    if any(c in raw for c in "()'&[]"):
        traits.append("parenthèses ou ponctuation")
    if "onedrive" in raw.lower():
        traits.append("OneDrive")
    if len(raw) > LONG_PROFILE:
        traits.append("chemin long")
    if not traits:
        return [Line(INFO, "Chemin du profil", "simple (ASCII, sans espace)")]
    return [
        Line(
            INFO,
            "Chemin du profil",
            "contient " + ", ".join(traits) + " : géré, rien à faire",
        )
    ]


CHECKS = (
    check_system, check_locale, check_powershell, check_webview, check_tools, check_widget,
    check_daemon, check_claude, check_hooks, check_autostart, check_environment,
    check_disk, check_profile,
)  # fmt: skip


def run_checks(d: DoctorDeps) -> list[Line]:
    """All checks, in order; one that raises is reported as KO and the others still run."""
    lines: list[Line] = []
    for check in CHECKS:
        try:
            lines.extend(check(d))
        except Exception as exc:  # noqa: BLE001 - a diagnostic tool must never crash
            lines.append(
                Line(
                    KO,
                    check.__name__.removeprefix("check_"),
                    f"vérification impossible ({type(exc).__name__}: {exc})",
                )
            )
    return lines


def render(lines: list[Line], d: DoctorDeps) -> list[str]:
    """The printable report, paths redacted."""
    out = [
        "Omniscient doctor (lecture seule ; aucun secret, chemins de profil masqués)"
    ]
    for line in lines:
        out.append(f"{line.level:<4} {line.label} : {line.detail}")
        if line.fix:
            out.append(f"     -> {line.fix}")
    kos = sum(1 for line in lines if line.level == KO)
    out.append("Résumé : " + (f"{kos} problème(s) KO" if kos else "tout est OK"))
    return [redact(text, d.home, d.windows) for text in out]


def exit_code(lines: list[Line]) -> int:
    return 1 if any(line.level == KO for line in lines) else 0


def real_deps(port: int) -> DoctorDeps:
    """The real machine."""
    from omniscient.group import hook_install
    from omniscient.group.autostart import Autostart
    from omniscient.group.claude_locate import find_claude
    from omniscient.group.cli_group_setup import daemon_healthy

    def engine() -> str | None:
        try:
            return version("omniscient")
        except PackageNotFoundError:
            return None

    def hooks() -> tuple[int, int]:
        st = hook_install.status("claude", hook_install.default_path("claude"))
        return len(st.installed), len(st.installed) + len(st.missing)

    return DoctorDeps(
        port=port,
        run=default_runner,
        healthy=daemon_healthy,
        engine_version=engine,
        claude=find_claude,
        hook_events=hooks,
        autostart=Autostart().installed,
        wsl=is_wsl(),
        win=real_facts(default_runner) if sys.platform == "win32" else WinFacts(),
    )
