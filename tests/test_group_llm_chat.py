"""The plain chat engine: request shapes per provider, errors, caps (httpx mock transport)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from omniscient.group import llm_chat as lc
from omniscient.group.providers import Provider

KEY = "sk-test-0123456789abcdefghij"


def public(host: str, port: int = 443, *a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


OPENAI = Provider("o", "openai", "OpenAI", "https://api.openai.com/v1", "gpt-x")
GEMINI = Provider(
    "g", "gemini", "Gemini", "https://generativelanguage.googleapis.com", "gemini-x"
)
CLAUDE = Provider(
    "a", "anthropic", "Anthropic", "https://api.anthropic.com", "claude-x"
)
LOCAL = Provider(
    "l", "openai-compatible", "Ollama", "http://127.0.0.1:11434/v1", "llama"
)
TURNS = [
    lc.Turn("user", "salut"),
    lc.Turn("assistant", "bonjour"),
    lc.Turn("user", "ça va ?"),
]


def run(provider: Provider, key: str | None, handler, turns=TURNS) -> str:
    return lc.complete(
        provider, key, turns, system="sys", client=client(handler), resolver=public
    )


def test_openai_request_and_reply() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(
            url=str(req.url),
            auth=req.headers.get("authorization"),
            body=json.loads(req.content),
        )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "très bien"}}]}
        )

    assert run(OPENAI, KEY, handler) == "très bien"
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}" and KEY not in seen["url"]
    assert seen["body"]["model"] == "gpt-x"
    assert [m["role"] for m in seen["body"]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


def test_local_model_without_a_key_sends_no_authorization() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    assert run(LOCAL, None, handler) == "ok" and seen["auth"] is None


def test_anthropic_request_and_reply() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(
            url=str(req.url),
            key=req.headers.get("x-api-key"),
            ver=req.headers.get("anthropic-version"),
            body=json.loads(req.content),
        )
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "text", "text": "b"},
                ]
            },
        )

    assert run(CLAUDE, KEY, handler) == "ab"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["key"] == KEY and seen["ver"]
    assert seen["body"]["system"] == "sys" and seen["body"]["max_tokens"] > 0
    assert [m["role"] for m in seen["body"]["messages"]] == [
        "user",
        "assistant",
        "user",
    ]


def test_gemini_request_keeps_the_key_out_of_the_url() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(
            url=str(req.url),
            key=req.headers.get("x-goog-api-key"),
            body=json.loads(req.content),
        )
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "gem"}]}}]}
        )

    model = Provider(
        "g", "gemini", "G", GEMINI.base_url, "models/gemini-x"
    )  # listing form
    assert run(model, KEY, handler) == "gem"
    assert (
        seen["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    )
    assert seen["key"] == KEY and KEY not in seen["url"]
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "refusée"),
        (403, "refusée"),
        (404, "introuvable"),
        (429, "Limite"),
        (500, "indisponible"),
        (503, "indisponible"),
    ],
)
def test_http_errors_become_french_messages_without_the_key(
    status: int, needle: str
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"error": {"message": f"bad key {KEY} sent"}}
        )

    with pytest.raises(lc.LlmError) as err:
        run(OPENAI, KEY, handler)
    assert needle in err.value.message and KEY not in err.value.message


def test_a_400_shows_a_scrubbed_clipped_reason() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "x" * 500 + KEY}})

    with pytest.raises(lc.LlmError) as err:
        run(OPENAI, KEY, handler)
    assert len(err.value.message) < 260 and KEY not in err.value.message


def test_network_failures_and_garbage() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    def slow(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    for handler, needle in ((boom, "joindre"), (slow, "trop de temps")):
        with pytest.raises(lc.LlmError) as err:
            run(OPENAI, KEY, handler)
        assert needle in err.value.message
    with pytest.raises(lc.LlmError):
        run(OPENAI, KEY, lambda r: httpx.Response(200, text="<html>nope"))
    with pytest.raises(lc.LlmError):
        run(OPENAI, KEY, lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(lc.LlmError):
        run(GEMINI, KEY, lambda r: httpx.Response(200, json={"candidates": []}))


def test_redirects_are_never_followed() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with pytest.raises(lc.LlmError):
        run(OPENAI, KEY, handler)


def test_oversized_replies_are_refused() -> None:
    big = {"choices": [{"message": {"content": "x" * (lc.MAX_REPLY_BYTES + 10)}}]}
    with pytest.raises(lc.LlmError):
        run(OPENAI, KEY, lambda r: httpx.Response(200, json=big))


def test_the_destination_is_rechecked_right_before_the_call() -> None:
    def rebinding(host, port, *a, **k):
        return [(2, 1, 6, "", ("10.0.0.9", port))]

    hit = Provider("c", "openai-compatible", "C", "https://llm.example/v1", "m")
    with pytest.raises(lc.LlmError):
        lc.complete(
            hit,
            KEY,
            TURNS,
            system="s",
            client=client(lambda r: httpx.Response(200, json={})),
            resolver=rebinding,
        )


def test_turns_keep_only_the_conversation_and_alternate() -> None:
    from datetime import UTC, datetime

    from omniscient.group.chat_store import Message

    now = datetime.now(UTC)
    msgs = (
        Message("assistant", "orpheline", now),
        Message("user", "a", now),
        Message("user", "b", now),
        Message("tool", "Bash", now, "Bash"),
        Message("assistant", "réponse", now),
        Message("error", "boom", now),
        Message("user", "c", now),
    )
    turns = lc.build_turns(msgs)
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].text == "a\n\nb" and turns[2].text == "c"


def test_history_is_capped_from_the_oldest_end() -> None:
    from datetime import UTC, datetime

    from omniscient.group.chat_store import Message

    now = datetime.now(UTC)
    chunk = "x" * 20_000
    msgs = tuple(
        Message("user" if i % 2 == 0 else "assistant", f"{i}{chunk}", now)
        for i in range(10)
    )
    turns = lc.build_turns(msgs)
    assert (
        sum(len(t.text) for t in turns) <= lc.MAX_HISTORY_CHARS
        and turns[0].role == "user"
    )
    assert turns[-1].text.startswith("9")


def test_listing_models() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == "api.openai.com":
            return httpx.Response(
                200, json={"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]}
            )
        if host == "api.anthropic.com":
            return httpx.Response(200, json={"data": [{"id": "claude-1"}]})
        return httpx.Response(
            200,
            json={"models": [
                {"name": "models/gemini-a", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embed-b", "supportedGenerationMethods": ["embedContent"]},
            ]},
        )  # fmt: skip

    c = client(handler)
    assert lc.list_models(OPENAI, KEY, client=c, resolver=public) == ["gpt-a", "gpt-b"]
    assert lc.list_models(CLAUDE, KEY, client=c, resolver=public) == ["claude-1"]
    assert lc.list_models(GEMINI, KEY, client=c, resolver=public) == ["gemini-a"]
