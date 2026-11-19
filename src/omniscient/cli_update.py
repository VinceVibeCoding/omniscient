"""`omniscient update` (and `omniscient --update`): update the engine and the widget."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer

from omniscient.group import update as up
from omniscient.group import widget_release as wr

EXIT_UPDATE_AVAILABLE = 1
EXIT_ERROR = 2


@dataclass(frozen=True)
class UpdateDeps:
    say: Callable[[str], None] = typer.echo
    fetch: wr.Fetch = wr.https_fetch
    attest: wr.Attest = wr.verify_attestation
    plan: Callable[[], up.UpdatePlan] | None = None
    native_windows: bool = sys.platform == "win32"
    spawn: Callable[[list[str]], None] = up.spawn_detached
    run: wr.Runner = wr._run
    which: Callable[[str], str | None] = shutil.which
    temp_dir: Callable[[], Path] = field(
        default=lambda: Path(tempfile.mkdtemp(prefix="omniscient-update-"))
    )
    pid: int = field(default_factory=os.getpid)
    widget_path: Callable[[], Path | None] = up.widget_exe


def _report(plan: up.UpdatePlan, say: Callable[[str], None]) -> None:
    say(f"Moteur : {plan.engine_installed} installé, {plan.engine_latest} disponible.")
    if plan.widget_installed is None:
        say("Widget : non installé sur cet ordinateur (ignoré).")
    else:
        say(
            f"Widget : {plan.widget_installed} installé, {plan.widget_latest} disponible."
        )


def run_update(check: bool, dry_run: bool, deps: UpdateDeps | None = None) -> int:
    """Returns the exit code: 0 up to date / done, 1 update available (--check), 2 error."""
    d = deps or UpdateDeps()
    try:
        plan = d.plan() if d.plan else up.plan_update(d.fetch)
        _report(plan, d.say)
        if not plan.outdated:
            d.say("Omniscient est déjà à jour.")
            return 0
        if check:
            d.say(f"Mise à jour disponible ({plan.tag}) : lance `omniscient update`.")
            return EXIT_UPDATE_AVAILABLE
        d.say(
            f"Je vais télécharger et vérifier {plan.tag} (SHA-256), puis l'installer."
        )
        if dry_run:
            d.say("--dry-run : rien n'est téléchargé ni installé.")
            return 0
        _apply(plan, d)
    except (up.UpdateError, wr.ReleaseError, OSError) as exc:
        d.say(f"Erreur : {exc}")
        return EXIT_ERROR
    return 0


def _apply(plan: up.UpdatePlan, d: UpdateDeps) -> None:
    dest = d.temp_dir()
    files = up.download_all(plan, dest, d.fetch, d.attest)
    d.say("Fichiers téléchargés et vérifiés.")
    if d.native_windows:
        log = dest / "update.log"
        app = d.widget_path() if plan.widget_installed is not None else None
        d.spawn(up.detached_command(files, log, d.pid, app))
        d.say(
            "Mise à jour lancée en arrière-plan : le démon et le widget redémarrent seuls."
        )
        d.say(f"Journal : {log}")
        return
    uv = d.which("uv")
    if uv is None:
        raise up.UpdateError(
            "uv est introuvable : installe-le (https://docs.astral.sh/uv/)."
        )
    code, out = d.run([uv, "tool", "install", "--force", str(files["wheel"])])
    if code != 0:
        raise up.UpdateError(f"uv a échoué : {out.strip()[-300:]}")
    d.say("Moteur mis à jour. Redémarre le démon (`omniscient group serve`).")
    d.say(
        "Le widget Windows se met à jour depuis Windows : `omniscient update` dans PowerShell."
    )


def register(app: typer.Typer) -> None:
    @app.command("update")
    def update(
        check: Annotated[
            bool,
            typer.Option(
                "--check", help="Seulement comparer (code 1 : mise à jour dispo)."
            ),
        ] = False,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Dire ce qui serait fait, sans rien faire."),
        ] = False,
    ) -> None:
        """Mettre à jour le moteur et le widget vers la dernière version publiée."""
        code = run_update(check, dry_run)
        if code:
            raise typer.Exit(code=code)
