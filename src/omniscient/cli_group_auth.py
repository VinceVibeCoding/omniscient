"""`omniscient group auth set|status|unset`: point the widget's accounts at a Supabase
Auth project (its URL and its public "anon" key, which is meant to be public).

Done from the command line only, never through the daemon's API: changing where people
sign in must not be possible from a compromised widget. A running daemon picks the change
up on the next sign-in, no restart needed. See docs/accounts.md.
"""

from __future__ import annotations

from typing import Annotated

import typer

from omniscient.group.auth import AuthError, AuthService
from omniscient.home import find_home

auth_app = typer.Typer(
    help="Comptes du widget : service de connexion (Supabase Auth).",
    no_args_is_help=True,
)


def _service() -> AuthService:
    return AuthService(find_home().state, lambda kind, data: None)


@auth_app.command("set")
def auth_set(
    url: Annotated[
        str,
        typer.Option(
            "--url",
            prompt="Adresse du projet (https://….supabase.co)",
            help="Adresse du projet Supabase.",
        ),
    ],
    anon_key: Annotated[
        str,
        typer.Option(
            "--anon-key",
            prompt="Clé publique « anon »",
            help="Clé publique du projet (« anon » / « publishable »).",
        ),
    ],
) -> None:
    """Enregistre le projet de connexion (adresse et clé publique)."""
    try:
        cfg = _service().configure(url, anon_key)
    except AuthError as exc:
        typer.echo(f"Erreur : {exc.message}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Comptes configurés sur {cfg.host}.")
    typer.echo(
        "À autoriser côté Supabase : voir docs/accounts.md (adresses de retour)."
    )


@auth_app.command("status")
def auth_status() -> None:
    """Affiche si les comptes sont configurés et qui est connecté."""
    view = _service().status()
    if not view["configured"]:
        typer.echo(
            "Comptes non configurés : `omniscient group auth set` (voir docs/accounts.md)."
        )
        return
    typer.echo(f"Service : {view['host']}")
    user = view["user"]
    typer.echo(
        f"Connecté : {user['email']} ({user['provider']})"
        if user
        else "Personne n'est connecté."
    )


@auth_app.command("unset")
def auth_unset() -> None:
    """Oublie le projet de connexion (la session enregistrée reste jusqu'à la déconnexion)."""
    _service().unconfigure()
    typer.echo("Configuration des comptes retirée.")


def register(group_app: typer.Typer) -> None:
    """Adds `auth` under `omniscient group`."""
    group_app.add_typer(auth_app, name="auth")
