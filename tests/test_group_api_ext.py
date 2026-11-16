"""Extension routes: handlers, auth, DELETE over a real daemon, SSE event."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from omniscient.group import api_ext
from omniscient.group.api import ApiError
from omniscient.group.ext_store import ExtensionStore
from tests.ext_support import manifest, write_ext
from tests.group_support import Daemon, start_daemon


@pytest.fixture
def app(tmp_path: Path) -> SimpleNamespace:
    write_ext(tmp_path / "extensions")
    published: list = []
    store = SimpleNamespace(publish=lambda k, d: published.append((k, d)))
    return SimpleNamespace(
        extensions=ExtensionStore(tmp_path / "extensions", tmp_path / "state"),
        store=store,
        published=published,
        root=tmp_path / "extensions",
    )


def test_list_shape(app: SimpleNamespace) -> None:
    status, body = api_ext.list_extensions(app, {}, {}, {})
    assert status == 200 and body["errors"] == []
    ext = body["extensions"][0]
    assert set(ext) == {"id", "name", "description", "version", "author", "enabled", "commands", "themes", "workflows", "provider_presets"}  # fmt: skip
    assert ext["commands"] == [
        {
            "name": "resume",
            "title": "Résumer",
            "args": [{"name": "n", "default": "5"}],
            "attach_page": True,
        }
    ]


def test_reload_picks_up_changes_and_publishes(app: SimpleNamespace) -> None:
    write_ext(app.root, manifest(id="second"))
    _, body = api_ext.reload_extensions(app, {}, {}, {})
    assert [e["id"] for e in body["extensions"]] == ["resume-page", "second"]
    assert app.published[-1][0] == "extensions" and app.published[-1][1] == body


def test_put_toggles_and_validates(app: SimpleNamespace) -> None:
    _, body = api_ext.put_extension(app, {"id": "resume-page"}, {}, {"enabled": False})
    assert body["extensions"][0]["enabled"] is False
    for bad in ({}, {"enabled": "yes"}):
        with pytest.raises(ApiError) as err:
            api_ext.put_extension(app, {"id": "resume-page"}, {}, bad)
        assert err.value.status == 400
    with pytest.raises(ApiError) as err:
        api_ext.put_extension(app, {"id": "ghost"}, {}, {"enabled": True})
    assert err.value.status == 404


def test_delete(app: SimpleNamespace) -> None:
    _, body = api_ext.delete_extension(app, {"id": "resume-page"}, {}, {})
    assert body["extensions"] == [] and not (app.root / "resume-page").exists()
    with pytest.raises(ApiError) as err:
        api_ext.delete_extension(app, {"id": "resume-page"}, {}, {})
    assert err.value.status == 404


def test_expand(app: SimpleNamespace) -> None:
    _, out = api_ext.expand_command(app, {}, {}, {"command": "resume", "args": "7"})
    assert out == {
        "text": "Résume la page en 7 points, en français.",
        "attach_page": True,
    }
    _, out = api_ext.expand_command(app, {}, {}, {"command": "resume"})
    assert "5 points" in out["text"]
    cases = [({"command": "ghost"}, 404), ({"command": "resume", "args": "1 2"}, 400), ({"command": "../x"}, 400), ({"command": "resume", "args": 5}, 400), ({"command": "resume", "args": "x" * 2001}, 400)]  # fmt: skip
    for body, status in cases:
        with pytest.raises(ApiError) as err:
            api_ext.expand_command(app, {}, {}, body)
        assert err.value.status == status
    api_ext.put_extension(app, {"id": "resume-page"}, {}, {"enabled": False})
    with pytest.raises(ApiError) as err:
        api_ext.expand_command(app, {}, {}, {"command": "resume"})
    assert err.value.status == 404


def test_disabled_daemon_is_503() -> None:
    with pytest.raises(ApiError) as err:
        api_ext.list_extensions(SimpleNamespace(), {}, {}, {})
    assert err.value.status == 503


# ---- through the real server -------------------------------------------------------------


@pytest.fixture
def live(tmp_path: Path):
    write_ext(tmp_path / "extensions")
    d = start_daemon(tmp_path)
    yield d
    d.server.close_all()


def test_routes_over_http(live: Daemon, tmp_path: Path) -> None:
    status, body, _ = live.call("GET", "/extensions")
    assert status == 200 and body["extensions"][0]["id"] == "resume-page"
    assert str(tmp_path) not in str(body)
    assert live.call("GET", "/extensions", auth=False)[0] == 401
    assert live.call("DELETE", "/extensions/resume-page", auth=False)[0] == 401
    assert live.call("DELETE", "/extensions/resume-page", auth="hook")[0] in (401, 403)
    status, body, _ = live.call("PUT", "/extensions/resume-page", {"enabled": False})
    assert status == 200 and body["extensions"][0]["enabled"] is False
    assert live.call("POST", "/extensions/expand", {"command": "resume"})[0] == 404
    live.call("PUT", "/extensions/resume-page", {"enabled": True})
    status, body, _ = live.call(
        "POST", "/extensions/expand", {"command": "resume", "args": "3"}
    )
    assert status == 200 and "3 points" in body["text"]
    write_ext(tmp_path / "extensions", manifest(id="late"))
    assert len(live.call("POST", "/extensions/reload")[1]["extensions"]) == 2
    status, body, _ = live.call("DELETE", "/extensions/late")
    assert status == 200 and [e["id"] for e in body["extensions"]] == ["resume-page"]
    assert live.call("DELETE", "/extensions/..%2Fx")[0] == 400
    assert live.call("GET", "/extensions/resume-page")[0] == 405


def test_cors_preflight_allows_delete(live: Daemon) -> None:
    conn = live.conn()
    conn.request("OPTIONS", "/extensions/x", headers={"Origin": "http://tauri.localhost", "Access-Control-Request-Method": "DELETE"})  # fmt: skip
    resp = conn.getresponse()
    resp.read()
    assert "DELETE" in resp.getheader("Access-Control-Allow-Methods")
