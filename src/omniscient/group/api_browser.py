"""Browser page routes (widget token, so a paired extension or widget):
PUT /browser/page (the extension reports the page, or that it is unticked) and
GET /browser/page (metadata only, for the widget). A report is announced as SSE
`browser_page` (metadata only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omniscient.group.browser_page import BrowserPageError, BrowserPages

if TYPE_CHECKING:
    from omniscient.group.server import App


def _api_error(status: int, message: str) -> Exception:
    from omniscient.group.api import ApiError  # api imports this module

    return ApiError(status, message)


def _pages(app: App) -> BrowserPages:
    pages = getattr(app, "browser", None)
    if pages is None:
        raise _api_error(503, "Page du navigateur désactivée sur ce démon.")
    return pages


def put_page(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    from omniscient.group.api_osd import publish

    try:
        meta = _pages(app).put(body)
    except BrowserPageError as exc:
        raise _api_error(exc.status, exc.message) from exc
    publish(app, "browser_page", meta)
    return 200, meta


def get_page(app: App, ids: dict, query: dict, body: dict) -> tuple[int, dict]:
    return 200, _pages(app).meta()
