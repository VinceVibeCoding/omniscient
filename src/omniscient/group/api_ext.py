"""Extension routes for the widget (widget-token auth like every other route):

GET    /extensions          the loaded extensions and the load errors
POST   /extensions/reload   re-read the extensions folder, same payload
PUT    /extensions/{id}     {"enabled": bool}
DELETE /extensions/{id}     delete the extension's folder
POST   /extensions/expand   {"command", "args"} -> {"text", "attach_page"}

Each change publishes an SSE `extensions` event with the new payload. `expand` only
returns text: the widget sends it as the user's own message through the normal chat
routes, so an extension gets no tool or provider choice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omniscient.group.api_osd import publish
from omniscient.group.ext_schema import NAME, ExtensionError
from omniscient.group.extensions import MAX_ARGS_TEXT

if TYPE_CHECKING:
    from omniscient.group.server import App


def _api_error(status: int, message: str) -> Exception:
    from omniscient.group.api import ApiError  # api imports this module

    return ApiError(status, message)


def _store(app: App) -> Any:
    store = getattr(app, "extensions", None)
    if store is None:
        raise _api_error(503, "Extensions désactivées sur ce démon.")
    return store


def _guard(work: Any) -> Any:
    try:
        return work()
    except ExtensionError as exc:
        raise _api_error(exc.status, exc.message) from exc


def _changed(app: App) -> tuple[int, dict]:
    view = _store(app).view()
    publish(app, "extensions", view)
    return 200, view


def list_extensions(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    return 200, _store(app).view()


def reload_extensions(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    _store(app).reload()
    return _changed(app)


def put_extension(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise _api_error(400, "enabled doit être vrai ou faux.")
    _guard(lambda: _store(app).set_enabled(ids["id"], enabled))
    return _changed(app)


def delete_extension(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    _guard(lambda: _store(app).remove(ids["id"]))
    return _changed(app)


def expand_command(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    name, args = body.get("command"), body.get("args", "")
    if not isinstance(name, str) or not NAME.match(name):
        raise _api_error(400, "command : nom de commande invalide.")
    if not isinstance(args, str) or len(args) > MAX_ARGS_TEXT:
        raise _api_error(400, f"args : texte de {MAX_ARGS_TEXT} caractères au plus.")
    return 200, _guard(lambda: _store(app).expand(name, args))
