"""Provider routes for the widget (widget-token auth like every other route):

GET  /providers              the list (Claude Code first) and the default; never a key
PUT  /providers/{id}         add or update (the api_key is write-only), optional "default"
POST /providers/{id}/test    proves the key and address work, returns the usable models
POST /providers/{id}/remove  forget a provider and its key
Handlers take (app, ids, query, body) like api.py; `app.providers` is a ProviderStore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omniscient.group import llm_chat
from omniscient.group.claude_locate import find_claude
from omniscient.group.providers import CLAUDE_CODE, ProviderError, ProviderStore

if TYPE_CHECKING:
    from omniscient.group.server import App


def _api_error(status: int, message: str) -> Exception:
    from omniscient.group.api import ApiError  # api imports this module

    return ApiError(status, message)


def _store(app: App) -> ProviderStore:
    store = getattr(app, "providers", None)
    if store is None:
        raise _api_error(503, "Fournisseurs désactivés sur ce démon.")
    return store


def _guard(work: Any) -> Any:
    try:
        return work()
    except ProviderError as exc:
        raise _api_error(exc.status, exc.message) from exc


def list_providers(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    return 200, _store(app).listing()


def put_provider(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    store = _store(app)
    _guard(lambda: store.upsert(ids["id"], body))
    return 200, store.listing()


def remove_provider(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    store = _store(app)
    _guard(lambda: store.remove(ids["id"]))
    return 200, store.listing()


def test_provider(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    store = _store(app)
    if ids["id"] == CLAUDE_CODE:
        return 200, {"ok": find_claude() is not None, "models": []}
    found = store.get(ids["id"])
    if found is None:
        raise _api_error(404, "Fournisseur inconnu.")
    _guard(store.allow_test)
    provider, key = found
    try:
        models = llm_chat.list_models(provider, key, resolver=store.resolver)
    except llm_chat.LlmError as exc:
        raise _api_error(502, exc.message) from exc
    return 200, {"ok": True, "models": models}
