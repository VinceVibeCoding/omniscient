"""`omniscient group auth`: configure, show and remove the sign-in project."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from omniscient import cli_group_auth
from omniscient.cli import app
from omniscient.group import auth as au

ANON = "eyJhbGciOiJIUzI1NiJ9.anon-public-key.sig"
runner = CliRunner()


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    monkeypatch.chdir(isolated_home)
    from omniscient.home import find_home

    def service() -> au.AuthService:  # the real DNS is never asked in tests
        return au.AuthService(
            find_home().state,
            lambda kind, data: None,
            resolver=lambda h, p, *a, **k: [(2, 1, 6, "", ("93.184.216.34", p))],
        )

    monkeypatch.setattr(cli_group_auth, "_service", service)
    monkeypatch.delenv(au.ENV_URL, raising=False)
    monkeypatch.delenv(au.ENV_KEY, raising=False)


def test_set_status_unset(isolated_home: Path) -> None:
    assert "non configurés" in runner.invoke(app, ["group", "auth", "status"]).output
    out = runner.invoke(
        app,
        [
            "group",
            "auth",
            "set",
            "--url",
            "https://abcdefgh.supabase.co",
            "--anon-key",
            ANON,
        ],
    )
    assert out.exit_code == 0, out.output
    assert "abcdefgh.supabase.co" in out.output and ANON not in out.output
    status = runner.invoke(app, ["group", "auth", "status"]).output
    assert "abcdefgh.supabase.co" in status and "Personne" in status
    assert "retirée" in runner.invoke(app, ["group", "auth", "unset"]).output
    assert "non configurés" in runner.invoke(app, ["group", "auth", "status"]).output


def test_a_bad_address_is_refused(isolated_home: Path) -> None:
    out = runner.invoke(
        app,
        [
            "group",
            "auth",
            "set",
            "--url",
            "http://abcdefgh.supabase.co",
            "--anon-key",
            ANON,
        ],
    )
    assert out.exit_code == 1 and "Erreur" in out.output
    assert cli_group_auth._service().config() is None
