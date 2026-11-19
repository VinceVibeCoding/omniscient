"""Port conflicts: a bind test, a French explanation, and `serve` refusing cleanly."""

from __future__ import annotations

import errno
import socket
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from omniscient import cli
from omniscient.console import lossless_streams
from omniscient.group import portcheck as pc

runner = CliRunner()


def _failing(code: int, winerror: int | None = None):
    def bind(port: int, windows: bool) -> None:
        exc = OSError(code, "boom")
        if winerror is not None:
            exc.winerror = winerror  # type: ignore[attr-defined]
        raise exc

    return bind


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_free_port_has_no_problem() -> None:
    assert pc.probe_bind(_free_port()) is None


def test_busy_port_is_detected_with_a_real_listener() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        problem = pc.probe_bind(int(sock.getsockname()[1]))
    assert problem is not None and problem.kind == pc.BUSY


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port(port: int) -> None:
    problem = pc.probe_bind(port)
    assert problem is not None and problem.kind == pc.INVALID


def test_windows_codes_are_classified_without_parsing_text() -> None:
    busy = pc.probe_bind(7341, windows=True, bind=_failing(10048, winerror=10048))
    reserved = pc.probe_bind(7341, windows=True, bind=_failing(10013, winerror=10013))
    other = pc.probe_bind(7341, windows=True, bind=_failing(errno.ENETDOWN))
    assert [p.kind for p in (busy, reserved, other) if p] == [
        pc.BUSY,
        pc.RESERVED,
        pc.OTHER,
    ]


def test_posix_errno_is_classified() -> None:
    assert (
        pc.probe_bind(1, windows=False, bind=_failing(errno.EADDRINUSE)).kind == pc.BUSY
    )  # type: ignore[union-attr]
    assert (
        pc.probe_bind(1, windows=False, bind=_failing(errno.EACCES)).kind == pc.RESERVED
    )  # type: ignore[union-attr]


def test_windows_probe_never_sets_reuseaddr() -> None:
    seen: list[bool] = []
    pc.probe_bind(7341, windows=True, bind=lambda port, win: seen.append(win))
    assert seen == [True]


def test_busy_message_names_the_port_and_every_place_to_change() -> None:
    text = pc.explain(pc.PortProblem(7341, pc.BUSY), 7342)
    for needle in (
        "7341",
        "occupé",
        "--port 7342",
        "autostart install --write --port 7342",
        "Adresse du démon",
        "http://127.0.0.1:7342",
        "OMNIGROUP_URL",
    ):
        assert needle in text


def test_reserved_message_gives_the_netsh_hint() -> None:
    text = pc.explain(pc.PortProblem(7341, pc.RESERVED), None)
    assert "indisponible" in text and "excludedportrange" in text and "--port" in text


def test_suggest_port_skips_unusable_ports() -> None:
    def bind(port: int, windows: bool) -> None:
        if port < 7343:
            raise OSError(errno.EADDRINUSE, "busy")

    assert pc.suggest_port(7341, windows=False, bind=bind) == 7343
    assert pc.suggest_port(7341, windows=False, bind=_failing(errno.EADDRINUSE)) is None


def test_preflight_free_busy_and_ours() -> None:
    free = pc.preflight(7341, lambda p: False, windows=False, bind=lambda p, w: None)
    assert not free.blocked and not free.already_running
    busy = _failing(errno.EADDRINUSE)
    ours = pc.preflight(7341, lambda p: True, windows=False, bind=busy)
    assert ours.already_running and not ours.blocked
    other = pc.preflight(7341, lambda p: False, windows=False, bind=busy)
    assert other.blocked and "7341" in other.message


def test_configured_port_follows_omnigroup_url() -> None:
    assert pc.configured_port({}) == 7341
    assert pc.configured_port({"OMNIGROUP_URL": "http://127.0.0.1:7351"}) == 7351
    assert pc.configured_port({"OMNIGROUP_URL": "nonsense"}) == 7341
    assert pc.configured_port({"OMNIGROUP_URL": "http://127.0.0.1:99999"}) == 7341


def test_serve_on_a_busy_port_exits_1_with_the_message() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = int(sock.getsockname()[1])
        result = runner.invoke(cli.app, ["group", "serve", "--port", str(port)])
    assert result.exit_code == 1
    assert str(port) in result.output and "OMNIGROUP_URL" in result.output


def test_serve_check_port_on_a_free_port_exits_0() -> None:
    port = _free_port()
    result = runner.invoke(
        cli.app, ["group", "serve", "--check-port", "--port", str(port)]
    )
    assert result.exit_code == 0 and str(port) in result.output


def test_lossless_streams_survive_the_ansi_code_page() -> None:
    code = (
        "import sys; from omniscient.console import lossless_streams;"
        "lossless_streams(); print('\\u2713 d\\u00e9j\\u00e0 \\u2192 ok')"
    )
    env = {"PYTHONIOENCODING": "cp1252", "PATH": "", "PYTHONUTF8": "0"}
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, env=env, check=False
    )
    assert done.returncode == 0, done.stderr
    assert "ok" in done.stdout.decode("cp1252")


def test_lossless_streams_ignores_streams_without_reconfigure() -> None:
    lossless_streams(None, object())  # pythonw has no stdout: must not raise
