"""Plain chat with a provider other than Claude Code: OpenAI (and compatible servers),
Google Gemini, and the Anthropic API. One request per turn, the whole (capped) history
in it, no tools: this engine only talks, it cannot run commands or read files.

Hardening: the destination is checked again right before each call (providers.py),
redirects are never followed, replies are read with a size cap, keys travel in headers
(never in a URL) and never appear in an error message.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from omniscient.group.chat_store import Message
from omniscient.group.providers import (
    Provider,
    ProviderError,
    Resolver,
    check_destination,
)
from omniscient.redact import redact_secrets

log = logging.getLogger(__name__)

MAX_REPLY_BYTES = 2 * 1024 * 1024
MAX_HISTORY_CHARS = 60_000
MAX_OUTPUT_TOKENS = 4096  # the Anthropic API requires one
MAX_MODELS = 80
REASON_MAX = 160
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)
SYSTEM_PROMPT = (
    "You are the chat assistant of Omnigroup, a small widget on the user's desktop. "
    "You have no tools: you cannot run commands, read files or browse. Answer from the "
    "conversation, concisely, in the language the user writes in."
)


class LlmError(Exception):
    """A failed turn, with a French message that is safe to show (no key, no raw body)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Turn:
    role: str  # user | assistant
    text: str


def build_turns(messages: Iterable[Message]) -> list[Turn]:
    """The user/assistant messages only, same-role neighbours merged, capped from the
    oldest end, always starting with a user turn (what every provider requires)."""
    turns: list[Turn] = []
    for m in messages:
        if m.role not in ("user", "assistant") or not m.text.strip():
            continue
        if turns and turns[-1].role == m.role:
            turns[-1] = Turn(m.role, f"{turns[-1].text}\n\n{m.text}")
        else:
            turns.append(Turn(m.role, m.text))
    while turns and (
        turns[0].role != "user" or sum(len(t.text) for t in turns) > MAX_HISTORY_CHARS
    ):
        turns.pop(0)
    if turns and len(turns[-1].text) > MAX_HISTORY_CHARS:
        turns[-1] = Turn(turns[-1].role, turns[-1].text[-MAX_HISTORY_CHARS:])
    return turns


# ---- requests per provider -----------------------------------------------------------


def _model_path(model: str) -> str:
    return model.removeprefix("models/")


def _request(
    provider: Provider, key: str | None, turns: list[Turn], system: str
) -> tuple[str, dict, dict]:
    """(url, headers, json body) of one chat turn."""
    base = provider.base_url.rstrip("/")
    if provider.kind == "gemini":
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user" if t.role == "user" else "model", "parts": [{"text": t.text}]} for t in turns],
        }  # fmt: skip
        url = f"{base}/v1beta/models/{_model_path(provider.model)}:generateContent"
        return url, {"x-goog-api-key": key or ""}, body
    if provider.kind == "anthropic":
        body = {
            "model": provider.model, "max_tokens": MAX_OUTPUT_TOKENS, "system": system,
            "messages": [{"role": t.role, "content": t.text} for t in turns],
        }  # fmt: skip
        headers = {"x-api-key": key or "", "anthropic-version": ANTHROPIC_VERSION}
        return f"{base}/v1/messages", headers, body
    messages = [{"role": "system", "content": system}] + [
        {"role": t.role, "content": t.text} for t in turns
    ]
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return (
        f"{base}/chat/completions",
        headers,
        {"model": provider.model, "messages": messages},
    )


def _reply_text(provider: Provider, data: Any) -> str:
    try:
        if provider.kind == "gemini":
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        elif provider.kind == "anthropic":
            text = "".join(
                b.get("text", "") for b in data["content"] if b.get("type") == "text"
            )
        else:
            text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        text = ""
    if not isinstance(text, str) or not text.strip():
        raise LlmError(f"{provider.label} n'a renvoyé aucune réponse.")
    return text


# ---- transport -----------------------------------------------------------------------


def _reason(response: httpx.Response) -> str:
    try:
        body = response.json()
        raw = (
            body["error"]["message"]
            if isinstance(body["error"], dict)
            else str(body["error"])
        )
    except (ValueError, KeyError, TypeError):
        return ""
    return redact_secrets(str(raw), keep_paths=True)[:REASON_MAX]


def _check_status(provider: Provider, response: httpx.Response) -> None:
    code, label = response.status_code, provider.label
    if code < 400:
        return
    if code in (401, 403):
        raise LlmError(f"Clé refusée par {label} : vérifiez-la dans les réglages.")
    if code == 404:
        raise LlmError(
            f"Modèle ou adresse introuvable chez {label} ({provider.model})."
        )
    if code == 429:
        raise LlmError(f"Limite de {label} atteinte : réessayez plus tard.")
    if code >= 500:
        raise LlmError(f"{label} est indisponible (HTTP {code}).")
    reason = _reason(response)
    raise LlmError(
        f"Requête refusée par {label}"
        + (f" : {reason}" if reason else f" (HTTP {code}).")
    )


def _send(
    provider: Provider,
    method: str,
    url: str,
    headers: dict,
    body: dict | None,
    client: httpx.Client | None,
    resolver: Resolver,
) -> Any:
    try:
        check_destination(url, resolver)
    except ProviderError as exc:
        raise LlmError(exc.message) from exc
    owned = client is None
    http = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        with http.stream(method, url, headers=headers, json=body) as response:
            _check_status(provider, response)
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    raise LlmError(f"Réponse de {provider.label} trop volumineuse.")
                chunks.append(chunk)
        data = httpx.Response(200, content=b"".join(chunks)).json()
    except httpx.TimeoutException as exc:
        raise LlmError(f"{provider.label} met trop de temps à répondre.") from exc
    except httpx.HTTPError as exc:
        log.warning("omnigroup llm: %s: %s", provider.id, type(exc).__name__)
        raise LlmError(f"Impossible de joindre {provider.label}.") from exc
    except ValueError as exc:
        raise LlmError(f"Réponse illisible de {provider.label}.") from exc
    finally:
        if owned:
            http.close()
    return data


def complete(
    provider: Provider,
    key: str | None,
    turns: list[Turn],
    *,
    system: str = SYSTEM_PROMPT,
    client: httpx.Client | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> str:
    """One chat turn: the assistant's reply text, or LlmError."""
    if not turns or turns[-1].role != "user":
        raise LlmError("Rien à envoyer.")
    url, headers, body = _request(provider, key, turns, system)
    data = _send(provider, "POST", url, headers, body, client, resolver)
    return _reply_text(provider, data)


def list_models(
    provider: Provider,
    key: str | None,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> list[str]:
    """Model ids the key can use (also proves the key and the address work)."""
    base = provider.base_url.rstrip("/")
    if provider.kind == "gemini":
        url, headers = f"{base}/v1beta/models", {"x-goog-api-key": key or ""}
    elif provider.kind == "anthropic":
        url, headers = (
            f"{base}/v1/models",
            {"x-api-key": key or "", "anthropic-version": ANTHROPIC_VERSION},
        )
    else:
        url, headers = (
            f"{base}/models",
            ({"Authorization": f"Bearer {key}"} if key else {}),
        )
    data = _send(provider, "GET", url, headers, None, client, resolver)
    try:
        if provider.kind == "gemini":
            names = [
                _model_path(m["name"]) for m in data["models"]
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]  # fmt: skip
        else:
            names = [m["id"] for m in data["data"]]
    except (KeyError, TypeError, AttributeError) as exc:
        raise LlmError(f"Liste de modèles illisible chez {provider.label}.") from exc
    return sorted({n for n in names if isinstance(n, str)})[:MAX_MODELS]
