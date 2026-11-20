"""The `omniscient` command: the widget's engine (`group`), updates, extensions, projects,
themes and the systemd units. The widget itself is the product; this is its toolbox."""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from omniscient.cli_ext import register as register_ext
from omniscient.cli_group import register_group
from omniscient.cli_onboarding import register_onboarding
from omniscient.cli_update import register as register_update
from omniscient.console import lossless_streams

lossless_streams()  # a cp1252 pipe must not turn a status line into a traceback

app = typer.Typer(
    no_args_is_help=True,
    help="Omniscient: a widget to talk to your AI agents, outside the IDE.",
)
register_onboarding(app)
register_group(app)
register_update(app)
register_ext(app)


def _print_version(shown: bool) -> None:
    if not shown:
        return
    from importlib.metadata import version

    typer.echo(f"omniscient {version('omniscient')}")
    raise typer.Exit()


def _run_update(requested: bool) -> None:
    if not requested:
        return
    from omniscient.cli_update import run_update

    raise typer.Exit(code=run_update(check=False, dry_run=False))


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version.",
        ),
    ] = False,
    update: Annotated[
        bool,
        typer.Option(
            "--update",
            callback=_run_update,
            is_eager=True,
            help="Update the engine and the widget (same as `omniscient update`).",
        ),
    ] = False,
) -> None:
    """Omniscient: a widget to talk to your AI agents, outside the IDE."""
    if sys.platform == "win32":  # piped output (the widget) is cp1252 by default
        from omniscient.group.hook_client import use_utf8_streams

        use_utf8_streams(sys.stdout, sys.stderr)
