"""Smoke test of the real daemon as a subprocess, on every OS (it is the Windows-native
proof in CI): start `omniscient group serve`, wait for /health, pair through the
terminal fallback, stop it cleanly, check the state files and that nothing was left."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from omniscient.group import procctl

START_TIMEOUT_S = 40.0
STOP_TIMEOUT_S = 20.0
LAUNCH = "from omniscient.cli import app; app()"


def user_env(home: Path) -> dict[str, str]:
    """The environment of a real user: no UTF-8 mode (the CI job sets PYTHONUTF8 for
    legacy fixtures, a person's machine does not), a private HOME and Omniscient home."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONUTF8", "PYTHONIOENCODING")
    }
    userdir = str(home / "user")
    return {
        **env,
        "OMNISCIENT_HOME": str(home),
        "HOME": userdir,
        "USERPROFILE": userdir,
        "PYTHONUNBUFFERED": "1",
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def call(
    port: int, method: str, path: str, token: str | None = None, body: Any = None
) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_for_health(port: int, proc: subprocess.Popen[str]) -> Any:
    deadline = time.monotonic() + START_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"the daemon exited early: {proc.returncode}")
        try:
            return call(port, "GET", "/health")
        except OSError:
            time.sleep(0.2)
    raise AssertionError("the daemon never answered /health")


def stop_gracefully(proc: subprocess.Popen[str]) -> None:
    """Windows: CTRL_BREAK_EVENT (a console is needed), else terminate; POSIX: SIGTERM."""
    if sys.platform == "win32":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        except OSError:
            proc.terminate()
    else:
        proc.send_signal(signal.SIGTERM)


@pytest.fixture
def daemon(tmp_path: Path):
    port = free_port()
    env = user_env(tmp_path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            LAUNCH,
            "group",
            "serve",
            "--port",
            str(port),
            "--no-collectors",
            "--allow-terminal-pairing",
        ],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **procctl.spawn_kwargs(hidden=False),
    )
    try:
        yield port, proc
    finally:
        if proc.poll() is None:
            procctl.kill(proc)
            proc.wait(10)
        if proc.stdout:
            proc.stdout.close()


def test_daemon_serves_pairs_and_stops_cleanly(
    daemon: tuple[int, subprocess.Popen[str]], tmp_path: Path
) -> None:
    port, proc = daemon
    health = wait_for_health(port, proc)
    assert health.get("ok") is True

    state = tmp_path / ".omniscient"
    hook_token = (state / "group.token").read_text(encoding="utf-8").strip()
    started = call(port, "POST", "/pair/start-terminal", hook_token, {})
    code = started["code"]
    assert len(code) == 6 and code.isdigit()
    paired = call(
        port, "POST", "/pair/finish", None, {"code": code, "client_name": "smoke"}
    )
    assert paired["ok"] is True and len(paired["token"]) >= 32
    sessions = call(port, "GET", "/sessions", paired["token"])
    assert sessions["sessions"] == []

    stop_gracefully(proc)
    try:
        proc.wait(STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pytest.fail("the daemon did not stop after the stop request")
    assert (state / "group.db").is_file() and (state / "group.token").is_file()


def test_setup_preview_prints_its_symbols_to_a_piped_stdout(tmp_path: Path) -> None:
    """The widget runs `group setup` with stdout piped: on Windows that stream is
    cp1252 unless the CLI switches it to UTF-8 (the check marks are not in cp1252)."""
    (tmp_path / "user" / ".claude").mkdir(parents=True)
    done = subprocess.run(
        [sys.executable, "-c", LAUNCH, "group", "setup", "--port", str(free_port()),
         "--skip-widget"],
        env=user_env(tmp_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        check=False,
    )  # fmt: skip
    out = done.stdout.decode("utf-8", errors="replace")
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")
    assert "Démon omnigroup" in out and "Claude Code" in out
    if sys.platform == "win32":
        assert "Mode Windows natif" in out
