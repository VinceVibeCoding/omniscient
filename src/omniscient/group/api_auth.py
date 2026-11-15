"""Account routes.

Widget token: GET /auth (who is signed in, never a token), POST /auth/start {provider}
(the URL to open in the browser), POST /auth/password {mode, email, password},
POST /auth/signout. Public (the browser cannot present a token): GET /auth/callback, where
Supabase sends the browser back after Google / GitHub, and GET /auth/confirmed, the page an
e-mail confirmation link lands on. Both answer a fixed HTML page and reflect no input.
The project URL and its public key are set from the command line only
(`omniscient group auth set`), never through the API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omniscient.group import auth_pages
from omniscient.group.auth import AuthError, AuthService

if TYPE_CHECKING:
    from omniscient.group.server import App

HTML_KEY = "_html"  # a handler returning {"_html": page} is sent as text/html


def _api_error(status: int, message: str) -> Exception:
    from omniscient.group.api import ApiError  # api imports this module

    return ApiError(status, message)


def _service(app: App) -> AuthService:
    service = getattr(app, "auth", None)
    if service is None:
        raise _api_error(503, "Comptes désactivés sur ce démon.")
    return service


def _guard(work: Any) -> Any:
    try:
        return work()
    except AuthError as exc:
        raise _api_error(exc.status, exc.message) from exc


def get_auth(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    return 200, _service(app).status()


def start(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    service = _service(app)
    return 200, _guard(lambda: service.start(body.get("provider")))


def password(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    service = _service(app)
    return 200, _guard(
        lambda: service.password(
            body.get("mode"), body.get("email"), body.get("password")
        )
    )


def signout(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    return 200, _service(app).signout()


def callback(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    status, page = _service(app).callback(query)
    return status, {HTML_KEY: page}


def confirmed(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    return 200, {HTML_KEY: auth_pages.confirmed()}
