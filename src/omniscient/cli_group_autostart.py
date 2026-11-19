"""`omniscient group autostart install|remove|status`: start the daemon at Windows logon."""

from __future__ import annotations

from typing import Annotated

import typer

from omniscient.group.autostart import TASK_NAME, Autostart, AutostartError
from omniscient.group.portcheck import configured_port

DEFAULT_PORT = configured_port()  # 7341, or the port of OMNIGROUP_URL
PortOpt = Annotated[int, typer.Option("--port", help="Port local du démon.")]


def _fail(exc: AutostartError) -> typer.Exit:
    typer.echo(f"Erreur : {exc}", err=True)
    return typer.Exit(code=1)


def register(group_app: typer.Typer) -> None:
    app = typer.Typer(
        help="Lancer le démon à l'ouverture de session Windows (tâche planifiée).",
        no_args_is_help=True,
    )
    group_app.add_typer(app, name="autostart")

    @app.command("install")
    def install(
        port: PortOpt = DEFAULT_PORT,
        write: Annotated[
            bool, typer.Option("--write", help="Créer la tâche (sinon : aperçu).")
        ] = False,
    ) -> None:
        """Aperçu de la tâche ; avec --write, la crée (sans droits administrateur)."""
        auto = Autostart()
        try:
            auto._require_windows()
            command = auto.command(port)
            if not write:
                typer.echo(
                    f"Tâche « {TASK_NAME} » à l'ouverture de session :\n  {command}"
                )
                typer.echo("\nAperçu seulement : relance avec --write.")
                return
            auto.install(port)
        except AutostartError as exc:
            raise _fail(exc) from exc
        typer.echo(
            f"Tâche « {TASK_NAME} » créée : le démon démarre à ta prochaine session."
        )

    @app.command("remove")
    def remove() -> None:
        """Supprime la tâche planifiée."""
        try:
            removed = Autostart().remove()
        except AutostartError as exc:
            raise _fail(exc) from exc
        typer.echo("Tâche supprimée." if removed else "Aucune tâche à supprimer.")

    @app.command("status")
    def status() -> None:
        """Dit si la tâche existe."""
        try:
            present = Autostart().installed()
        except AutostartError as exc:
            raise _fail(exc) from exc
        typer.echo(f"Démarrage automatique : {'actif' if present else 'inactif'}.")
