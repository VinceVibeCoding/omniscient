"""The `omniscient` command line is the widget's toolbox: no idea-factory commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from omniscient import cli

runner = CliRunner()

WIDGET_COMMANDS = ("group", "update", "ext", "project", "theme", "schedule")
REMOVED_FACTORY_COMMANDS = (
    "idea",
    "studio",
    "warroom",
    "chat",
    "think",
    "plan",
    "build",
    "work",
    "cycle",
    "ingest",
    "learn-sync",
    "agents-push",
    "init",
)


def test_version_prints_the_installed_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("omniscient ")


def test_help_lists_the_widget_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    for command in WIDGET_COMMANDS:
        assert command in result.output


@pytest.mark.parametrize("command", REMOVED_FACTORY_COMMANDS)
def test_factory_commands_are_gone(command: str) -> None:
    result = runner.invoke(cli.app, [command, "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_theme_preview_is_gone_but_list_and_export_stay() -> None:
    gone = runner.invoke(cli.app, ["theme", "preview"])
    assert gone.exit_code != 0
    for stay in ("list", "set", "export"):
        assert runner.invoke(cli.app, ["theme", stay, "--help"]).exit_code == 0
