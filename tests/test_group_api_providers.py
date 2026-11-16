"""Provider routes: write-only keys, test calls, chat creation with a provider."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omniscient.group import api_chat, api_providers
from omniscient.group.api import ApiError
from omniscient.group.chat import ChatManager
from omniscient.group.llm_chat import LlmError
from omniscient.group.providers import ProviderStore
from omniscient.home import Home

KEY = "sk-test-0123456789abcdefghij"


def public(host: str, port: int = 443, *a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


@pytest.fixture
def app(isolated_home: Path) -> SimpleNamespace:
    home = Home(isolated_home)
    store = ProviderStore(home.state, resolver=public)
    published: list = []
    chat = ChatManager(
        home,
        lambda k, d: published.append((k, d)),
        providers=store,
        llm=lambda *a, **k: "ok",
    )
    return SimpleNamespace(providers=store, chat=chat, published=published)


def test_listing_starts_with_claude_code(app: SimpleNamespace) -> None:
    status, body = api_providers.list_providers(app, {}, {}, {})
    assert status == 200 and body["default"] == "claude-code"
    assert [p["id"] for p in body["providers"]] == ["claude-code"]


def test_saving_returns_the_listing_without_the_key(app: SimpleNamespace) -> None:
    body = {"kind": "gemini", "model": "gemini-x", "api_key": KEY, "default": True}
    status, out = api_providers.put_provider(app, {"id": "gem"}, {}, body)
    assert status == 200 and out["default"] == "gem"
    saved = next(p for p in out["providers"] if p["id"] == "gem")
    assert saved["has_key"] and saved["key_hint"] == KEY[-4:]
    assert KEY not in json.dumps(out) and KEY not in json.dumps(app.published)


def test_bad_input_is_a_400(app: SimpleNamespace) -> None:
    with pytest.raises(ApiError) as err:
        api_providers.put_provider(
            app, {"id": "gem"}, {}, {"kind": "gemini", "model": "m", "api_key": "x"}
        )
    assert err.value.status == 400


def test_remove(app: SimpleNamespace) -> None:
    api_providers.put_provider(
        app, {"id": "o"}, {}, {"kind": "openai", "model": "m", "api_key": KEY}
    )
    _, out = api_providers.remove_provider(app, {"id": "o"}, {}, {})
    assert [p["id"] for p in out["providers"]] == ["claude-code"]
    with pytest.raises(ApiError) as err:
        api_providers.remove_provider(app, {"id": "o"}, {}, {})
    assert err.value.status == 404


def test_test_call_lists_models(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_providers.put_provider(
        app, {"id": "o"}, {}, {"kind": "openai", "model": "m", "api_key": KEY}
    )
    seen: dict[str, Any] = {}

    def fake(provider: Any, key: Any, **kw: Any) -> list[str]:
        seen["key"] = key
        return ["a", "b"]

    monkeypatch.setattr(api_providers.llm_chat, "list_models", fake)
    status, out = api_providers.test_provider(app, {"id": "o"}, {}, {})
    assert (
        status == 200
        and out == {"ok": True, "models": ["a", "b"]}
        and seen["key"] == KEY
    )


def test_test_call_failure_is_a_502_with_a_safe_message(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_providers.put_provider(
        app, {"id": "o"}, {}, {"kind": "openai", "model": "m", "api_key": KEY}
    )

    def fail(*a: Any, **k: Any) -> list[str]:
        raise LlmError("Clé refusée par OpenAI")

    monkeypatch.setattr(api_providers.llm_chat, "list_models", fail)
    with pytest.raises(ApiError) as err:
        api_providers.test_provider(app, {"id": "o"}, {}, {})
    assert err.value.status == 502 and "refusée" in err.value.message
    with pytest.raises(ApiError) as err:
        api_providers.test_provider(app, {"id": "nope"}, {}, {})
    assert err.value.status == 404


def test_claude_code_test_checks_the_binary(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    assert (
        api_providers.test_provider(app, {"id": "claude-code"}, {}, {})[1]["ok"] is True
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert (
        api_providers.test_provider(app, {"id": "claude-code"}, {}, {})[1]["ok"]
        is False
    )


def test_chat_creation_takes_a_provider(app: SimpleNamespace) -> None:
    api_providers.put_provider(
        app, {"id": "o"}, {}, {"kind": "openai", "model": "m", "api_key": KEY}
    )
    status, body = api_chat.create_chat(app, {}, {}, {"provider": "o", "text": "salut"})
    assert status == 202
    app.chat.join(body["chat_id"], 5)
    assert app.chat.get(body["chat_id"])[1]["chat"]["provider"] == "o"
    with pytest.raises(ApiError) as err:
        api_chat.create_chat(app, {}, {}, {"provider": "nope", "text": "salut"})
    assert err.value.status == 404
