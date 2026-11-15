"""LLM providers: the registry, the write-only key vault and the destination guard."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from omniscient.group import providers as pv

KEY = "sk-test-0123456789abcdefghij"


def public(host: str, port: int = 443, *a, **k):  # a resolver: everything is public
    return [(2, 1, 6, "", ("93.184.216.34", port))]


@pytest.fixture
def store(tmp_path: Path) -> pv.ProviderStore:
    return pv.ProviderStore(tmp_path / "state", resolver=public)


def test_claude_code_is_the_builtin_default(store: pv.ProviderStore) -> None:
    view = store.listing()
    assert view["default"] == "claude-code"
    first = view["providers"][0]
    assert first["id"] == "claude-code" and first["builtin"] is True
    assert "api_key" not in json.dumps(view)


def test_save_keeps_the_key_write_only(store: pv.ProviderStore, tmp_path: Path) -> None:
    saved = store.upsert(
        "gemini-perso",
        {"kind": "gemini", "label": "Mon Gemini", "model": "gemini-x", "api_key": KEY},
    )
    assert saved["has_key"] is True and saved["key_hint"] == KEY[-4:]
    dumped = json.dumps(store.listing())
    assert KEY not in dumped and "api_key" not in dumped
    provider, key = store.get("gemini-perso")
    assert key == KEY and provider.kind == "gemini" and provider.model == "gemini-x"
    for name in ("providers.json", "provider_keys.json"):
        mode = stat.S_IMODE(os.stat(tmp_path / "state" / name).st_mode)
        assert mode == 0o600, name
    assert stat.S_IMODE(os.stat(tmp_path / "state").st_mode) == 0o700
    assert KEY not in (tmp_path / "state" / "providers.json").read_text()


def test_updating_without_a_key_keeps_the_old_one(store: pv.ProviderStore) -> None:
    store.upsert("o", {"kind": "openai", "model": "m1", "api_key": KEY})
    store.upsert("o", {"kind": "openai", "model": "m2"})
    provider, key = store.get("o")
    assert provider.model == "m2" and key == KEY


def test_fixed_kinds_ignore_a_custom_address(store: pv.ProviderStore) -> None:
    store.upsert(
        "o",
        {
            "kind": "openai",
            "model": "m",
            "api_key": KEY,
            "base_url": "https://evil.example/v1",
        },
    )
    assert store.get("o")[0].base_url == "https://api.openai.com/v1"


def test_validation_of_ids_kinds_models_and_keys(store: pv.ProviderStore) -> None:
    bad = [
        ("Bad Id", {"kind": "openai", "model": "m", "api_key": KEY}),
        ("claude-code", {"kind": "openai", "model": "m", "api_key": KEY}),
        ("x", {"kind": "skynet", "model": "m", "api_key": KEY}),
        ("x", {"kind": "openai", "model": "bad model;", "api_key": KEY}),
        ("x", {"kind": "openai", "model": "m", "api_key": "short"}),
        ("x", {"kind": "openai", "model": "m", "api_key": "has space in the key 123"}),
        ("x", {"kind": "openai", "model": "m", "api_key": "a" * 600}),
        ("x", {"kind": "openai", "model": "m"}),  # a hosted provider needs a key
        ("x", {"kind": "openai", "model": "m", "api_key": KEY, "label": "l" * 100}),
    ]
    for pid, body in bad:
        with pytest.raises(pv.ProviderError) as err:
            store.upsert(pid, body)
        assert err.value.status == 400, (pid, body)
    assert store.listing()["providers"][1:] == []


def test_local_models_need_no_key(store: pv.ProviderStore) -> None:
    saved = store.upsert(
        "ollama",
        {
            "kind": "openai-compatible",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "llama",
        },
    )
    assert saved["has_key"] is False and store.get("ollama")[1] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest",  # cloud metadata
        "http://10.0.0.5:8080/v1",  # private network
        "http://192.168.1.20/v1",
        "http://example.com/v1",  # plain http to a remote host
        "ftp://example.com/v1",
        "https://user:pw@example.com/v1",
        "https://example.com/v1?x=1",
        "https://example.com/v1#frag",
        "https://[fe80::1]/v1",
        "not a url",
        "",
    ],
)
def test_forbidden_destinations(store: pv.ProviderStore, url: str) -> None:
    with pytest.raises(pv.ProviderError) as err:
        store.upsert(
            "c",
            {
                "kind": "openai-compatible",
                "base_url": url,
                "model": "m",
                "api_key": KEY,
            },
        )
    assert err.value.status == 400


def test_allowed_destinations(store: pv.ProviderStore) -> None:
    for i, url in enumerate(
        (
            "https://api.groq.com/openai/v1",
            "http://localhost:11434/v1",
            "http://127.0.0.1:1234/v1",
            "http://[::1]:8000/v1",
        )
    ):
        store.upsert(
            f"c{i}",
            {
                "kind": "openai-compatible",
                "base_url": url,
                "model": "m",
                "api_key": KEY,
            },
        )


def test_a_name_that_resolves_to_a_private_address_is_refused() -> None:
    def rebinding(host, port, *a, **k):
        return [(2, 1, 6, "", ("10.1.2.3", port))]

    with pytest.raises(pv.ProviderError):
        pv.check_destination("https://innocent.example/v1", rebinding)
    with pytest.raises(
        pv.ProviderError
    ):  # not "localhost" itself, even if it points there
        pv.check_destination(
            "http://sneaky.example/v1",
            lambda h, p, *a, **k: [(2, 1, 6, "", ("127.0.0.1", p))],
        )


def test_default_remove_and_limits(store: pv.ProviderStore) -> None:
    store.upsert("a", {"kind": "openai", "model": "m", "api_key": KEY, "default": True})
    assert store.listing()["default"] == "a"
    store.remove("a")
    view = store.listing()
    assert view["default"] == "claude-code" and len(view["providers"]) == 1
    assert store.get("a") is None
    with pytest.raises(pv.ProviderError) as err:
        store.remove("claude-code")
    assert err.value.status == 400
    with pytest.raises(pv.ProviderError) as err:
        store.remove("never-existed")
    assert err.value.status == 404
    for i in range(pv.MAX_PROVIDERS):
        store.upsert(f"p{i}", {"kind": "openai", "model": "m", "api_key": KEY})
    with pytest.raises(pv.ProviderError):
        store.upsert("one-too-many", {"kind": "openai", "model": "m", "api_key": KEY})


def test_corrupt_files_are_ignored_with_a_log(
    store: pv.ProviderStore, tmp_path: Path, caplog
) -> None:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "providers.json").write_text("{not json", encoding="utf-8")
    fresh = pv.ProviderStore(state, resolver=public)
    assert fresh.listing()["providers"][0]["id"] == "claude-code"
    assert "providers.json" in caplog.text


def test_test_calls_are_rate_limited(tmp_path: Path) -> None:
    now = [0.0]
    s = pv.ProviderStore(tmp_path / "s", resolver=public, clock=lambda: now[0])
    for _ in range(pv.MAX_TESTS_PER_HOUR):
        s.allow_test()
    with pytest.raises(pv.ProviderError) as err:
        s.allow_test()
    assert err.value.status == 429
    now[0] += 3601
    s.allow_test()
