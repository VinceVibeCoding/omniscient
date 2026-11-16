"""TEMPORARY diagnostics for the Windows e2e race (removed before the final commit)."""

import io
import json
import sys
import threading
from pathlib import Path

import pytest

from omniscient.group import server as srv
from omniscient.group.hook_client import HookContext, run_hook, urllib_transport
from omniscient.home import Home
from tests.test_group_e2e import ASK_USER_QUESTION, WIDGET, call, open_pending


@pytest.mark.parametrize("n", range(12))
def test_diag(tmp_path: Path, n: int) -> None:
    server = srv.create_server(
        Home(tmp_path / "home"), port=0, show_code=lambda c: True
    )
    server.start_background()
    server.app.presence.touch()
    WIDGET[server.port] = server.app.widgets.mint("e2e")
    log: list[str] = []

    def transport(method, url, headers, data, timeout):
        try:
            out = urllib_transport(method, url, headers, data, timeout)
        except Exception as exc:
            log.append(f"{method} {url} -> EXC {exc!r}")
            raise
        log.append(
            f"{method} {url.split('/', 3)[-1]} -> {json.dumps({k: v for k, v in out.items() if k in ('status', 'answer', 'answered_at', 'expires_at')} if isinstance(out, dict) else out)}"
        )
        return out

    ctx = HookContext(
        state_dir=server.app.home.state,
        environ={"OMNIGROUP_URL": f"http://127.0.0.1:{server.port}"},
        transport=transport,
        copilot_hooks=tmp_path / "nc.json",
    )
    out = io.StringIO()
    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    t = threading.Thread(
        target=run_hook,
        args=("claude", io.StringIO(json.dumps(ASK_USER_QUESTION)), out, ctx),
        daemon=True,
    )
    t.start()
    p = open_pending(server)
    call(
        server,
        "POST",
        f"/pending/{p['id']}/answer",
        {"answers": {"Quelle base ?": "Postgres"}},
    )
    t.join(10)
    sys.stderr = old
    server.close_all()
    print("LOG", log, "ERR", err.getvalue(), "OUT", out.getvalue()[:100], flush=True)
    assert out.getvalue(), (log, err.getvalue())
