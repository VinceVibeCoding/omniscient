"""`omniscient group setup`: one idempotent checklist to get omniscient running.

1. the daemon answers on 127.0.0.1 (else: how to start it, or its systemd unit);
2. Claude Code hooks + statusLine in ~/.claude/settings.json (hook_install: a diff first,
   written only with --write, after a backup);
3. the Windows widget: newest published `widget-v*` release, SHA-256 checked against
   SHA256SUMS, saved to the Windows Downloads folder (WSL) or ~/Downloads;
4. how to pair the widget.
Nothing is written without --write: the default run is a preview.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from omniscient.group import widget_release as wr
from omniscient.group.portcheck import configured_port

DEFAULT_PORT = configured_port()  # 7341, or the port of OMNISCIENT_URL
HEALTH_TIMEOUT_S = 3.0
PAIRING_HELP = (
    "Couplage : ouvre Omniscient sur Windows, clique le widget → Réglages → « Demander un "
    "code », puis tape le code à 6 chiffres affiché sur le bureau."
)


@dataclass(frozen=True)
class SetupOptions:
    write: bool = False
    port: int = DEFAULT_PORT
    protect: bool = False
    skip_widget: bool = False
    widget_dir: Path | None = None  # where to save the installer (default: Downloads)
    update_widget: bool = False  # download it even when Omniscient is already installed


@dataclass(frozen=True)
class SetupDeps:
    say: Callable[[str], None]
    health: Callable[[int], bool]
    fetch: wr.Fetch
    hooks: Callable[..., None]  # hook_install.run_hooks_command keywords
    downloads: Callable[[], Path]
    attest: wr.Attest = wr.verify_attestation
    native_windows: bool = False  # the daemon runs on Windows itself (no WSL)
    widget_installed: Callable[[], bool] = lambda: False
    find_claude: Callable[[], str | None] = lambda: None


def daemon_healthy(port: int) -> bool:
    """GET /health on the loopback daemon, bypassing any proxy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(
            f"http://127.0.0.1:{port}/health", timeout=HEALTH_TIMEOUT_S
        ) as resp:
            return bool(json.loads(resp.read(64 * 1024)).get("ok"))
    except (OSError, ValueError):
        return False


def default_downloads() -> Path:
    from omniscient.group.actions import default_runner, is_wsl

    found = wr.windows_downloads(default_runner) if is_wsl() else None
    if found is not None:
        return found
    home_downloads = Path.home() / "Downloads"
    return home_downloads if home_downloads.is_dir() else Path.home()


def _run_hooks(**kw: Any) -> None:
    from omniscient.group.hook_install import run_hooks_command

    run_hooks_command("install", target="claude", **kw)


def widget_installed() -> bool:
    """The Omniscient app installed for this Windows user (per-user NSIS install)."""
    base = os.environ.get("LOCALAPPDATA")
    return (
        bool(base) and (Path(base) / "Omniscient" / "omniscient-widget.exe").is_file()
    )


def default_deps() -> SetupDeps:
    from omniscient.group.claude_locate import find_claude

    return SetupDeps(
        typer.echo,
        daemon_healthy,
        wr.https_fetch,
        _run_hooks,
        default_downloads,
        native_windows=sys.platform == "win32",
        find_claude=find_claude,
        widget_installed=widget_installed,
    )


# ---- steps -----------------------------------------------------------------------------


def _step_daemon(opts: SetupOptions, deps: SetupDeps) -> None:
    deps.say("1. Démon omniscient")
    if deps.health(opts.port):
        deps.say(f"   ✓ répond sur http://127.0.0.1:{opts.port}")
        return
    deps.say(f"   ✗ ne répond pas sur le port {opts.port}.")
    if deps.native_windows:
        deps.say(
            "   → lance `omniscient group serve` dans un terminal, ou "
            "`omniscient group autostart install --write` pour le démarrer à chaque "
            "ouverture de session."
        )
        return
    deps.say(
        "   → lance `omniscient group serve` (ou `omniscient schedule install` pour"
    )
    deps.say(
        "     le service systemd omniscient, puis `systemctl --user enable --now omniscient`)."
    )


def _step_hooks(opts: SetupOptions, deps: SetupDeps) -> None:
    from omniscient.group.hook_install import HookInstallError

    deps.say("2. Hooks et statusLine de Claude Code (~/.claude/settings.json)")
    try:
        deps.hooks(
            write=opts.write, say=deps.say, statusline=True, protect=opts.protect
        )
    except HookInstallError as exc:
        deps.say(f"   ✗ {exc}")


def _step_widget(
    opts: SetupOptions, deps: SetupDeps, number: int = 3, *, native: bool = False
) -> None:
    deps.say(f"{number}. Widget Windows")
    if opts.skip_widget:
        deps.say("   — ignoré (--skip-widget).")
        return
    try:
        release = wr.latest_widget_release(deps.fetch)
    except wr.ReleaseError as exc:
        deps.say(f"   ✗ GitHub injoignable : {exc}")
        return
    if release is None:
        deps.say(
            "   ✗ Aucune version publiée du widget pour l'instant : voir les artefacts"
        )
        deps.say(
            f"     « omniscient-windows-nsis » sur https://github.com/{wr.REPO}/actions"
        )
        return
    dest = opts.widget_dir or deps.downloads()
    if not opts.write:
        deps.say(
            f"   → {release.installer.name} ({release.tag}) sera téléchargé et vérifié"
        )
        deps.say(f"     (SHA256SUMS) dans {dest}")
        return
    status: list[str] = []

    def attest(file: Path) -> str:
        status.append(deps.attest(file))
        return status[-1]

    try:
        path = wr.download_verified(release, dest, deps.fetch, attest)
    except wr.ReleaseError as exc:
        deps.say(f"   ✗ {exc}")
        return
    deps.say(f"   ✓ {path.name} téléchargé, SHA256 vérifié : {path}")
    if status and status[-1] == "verified":
        deps.say(
            "   ✓ attestation de provenance GitHub vérifiée (gh attestation verify)."
        )
    if native:
        return  # the installer runs it and the widget asks for its own pairing code
    if not (status and status[-1] == "verified"):
        deps.say(
            "   ⚠ gh absent : seul le SHA256 a été vérifié (pas la provenance du build)."
        )
    deps.say(f"   → lance-le (double-clic sous Windows, ou depuis WSL : '{path}').")


def _step_claude(deps: SetupDeps) -> None:
    from omniscient.group.claude_locate import CLAUDE_NOT_FOUND

    deps.say("3. Claude Code")
    found = deps.find_claude()
    if found:
        deps.say(f"   ✓ trouvé : {found}")
    else:
        deps.say(f"   ✗ claude introuvable. {CLAUDE_NOT_FOUND}")


def _run_native_windows(opts: SetupOptions, deps: SetupDeps) -> None:
    """Native Windows: no WSL step; the widget is downloaded unless it is already installed."""
    deps.say("Mode Windows natif (sans WSL).")
    _step_daemon(opts, deps)
    _step_hooks(opts, deps)
    _step_claude(deps)
    if deps.widget_installed() and not (opts.update_widget and not opts.skip_widget):
        deps.say("4. Widget Windows")
        deps.say("   ✓ Omniscient est déjà installé (menu Démarrer).")
    else:
        _step_widget(opts, deps, 4, native=True)
    if not opts.write:
        deps.say("")
        deps.say("Aperçu seulement : relance avec --write pour appliquer.")


def run_setup(opts: SetupOptions, deps: SetupDeps) -> None:
    if deps.native_windows:
        _run_native_windows(opts, deps)
        return
    _step_daemon(opts, deps)
    _step_hooks(opts, deps)
    _step_widget(opts, deps)
    deps.say("4. " + PAIRING_HELP)
    if not opts.write:
        deps.say("")
        deps.say("Aperçu seulement : relance avec --write pour appliquer.")


# ---- CLI -------------------------------------------------------------------------------


def register(group_app: typer.Typer) -> None:
    """Adds `setup` to the `omniscient group` Typer app."""

    @group_app.command("setup")
    def setup(
        write: Annotated[
            bool, typer.Option("--write", help="Appliquer (sinon : aperçu seulement).")
        ] = False,
        port: Annotated[
            int, typer.Option("--port", help="Port local du démon.")
        ] = DEFAULT_PORT,
        protect: Annotated[
            bool,
            typer.Option(
                "--protect", help="Ajouter les règles deny autour de l'état omniscient."
            ),
        ] = False,
        skip_widget: Annotated[
            bool,
            typer.Option("--skip-widget", help="Ne pas télécharger le widget Windows."),
        ] = False,
        widget_dir: Annotated[
            Path | None,
            typer.Option(
                "--widget-dir", help="Dossier où enregistrer l'installeur du widget."
            ),
        ] = None,
        update_widget: Annotated[
            bool,
            typer.Option(
                "--update-widget",
                help="Télécharger l'installeur même si Omniscient est déjà installé.",
            ),
        ] = False,
    ) -> None:
        """Tout installer en une commande : démon, hooks, widget, couplage."""
        run_setup(
            SetupOptions(write, port, protect, skip_widget, widget_dir, update_widget),
            default_deps(),
        )
