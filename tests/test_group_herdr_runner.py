"""The herdr CLI runner the widget engine uses (herdr is optional: a missing binary is an
expected, quiet failure, never a traceback)."""

from __future__ import annotations

import json
import subprocess

import pytest

from omniscient.group import herdr_runner as herdr_mod
from omniscient.group.herdr_runner import HerdrError, default_runner


def _completed(
    code: int, out: str = "", err: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["herdr"], code, stdout=out, stderr=err)


def test_default_runner_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(argv)
        return _completed(0, out='{"result": {}}')

    monkeypatch.setattr(herdr_mod.subprocess, "run", fake_run)
    assert default_runner(["workspace", "list"]) == '{"result": {}}'
    assert seen == [["herdr", "workspace", "list"]]


def test_default_runner_raises_json_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = json.dumps(
        {"id": "x", "error": {"code": "server_not_running", "message": "no server"}}
    )
    monkeypatch.setattr(
        herdr_mod.subprocess, "run", lambda *a, **k: _completed(1, err=err)
    )
    with pytest.raises(HerdrError, match="no server"):
        default_runner(["workspace", "list"])


def test_a_stopped_herdr_server_is_marked_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = json.dumps({"error": {"message": "no herdr server is running"}})
    monkeypatch.setattr(
        herdr_mod.subprocess, "run", lambda *a, **k: _completed(1, err=err)
    )
    with pytest.raises(HerdrError) as caught:
        default_runner(["status", "server"])
    assert caught.value.unavailable is True


def test_default_runner_wraps_missing_binary_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*a: object, **k: object) -> None:
        raise FileNotFoundError("herdr")

    monkeypatch.setattr(herdr_mod.subprocess, "run", missing)
    with pytest.raises(HerdrError, match="introuvable") as caught:
        default_runner(["status", "server"])
    assert caught.value.unavailable is True

    def slow(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired("herdr", 60)

    monkeypatch.setattr(herdr_mod.subprocess, "run", slow)
    with pytest.raises(HerdrError, match="délai"):
        default_runner(["status", "server"])
