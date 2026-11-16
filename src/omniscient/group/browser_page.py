"""The page open in the browser, as the Omnigroup extension reports it, so a widget chat can
attach it (« Joindre la page du navigateur »).

Memory only, never written to disk: one entry, the latest report, forgotten after TTL_S.
The extension reports either the page (validated and cleaned by page_context: capped,
secrets masked, no query string) or that the person unticked it for this page; then
nothing is attached, not even an older page. The widget only ever sees metadata (title,
address), never the page text.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from omniscient.group.models import iso, utcnow
from omniscient.group.page_context import PageContext, PageError, clean_page, clean_url

TTL_S = 900
TITLE_MAX = 300


class BrowserPageError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Report:
    url: str
    title: str
    excluded: bool
    page: PageContext | None
    at: float
    captured_at: str


class BrowserPages:
    """The latest report, thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._report: Report | None = None

    def put(self, raw: Any) -> dict[str, Any]:
        report = self._parse(raw)
        with self._lock:
            self._report = report
        return self.meta()

    def _parse(self, raw: Any) -> Report:
        now, stamp = self._clock(), iso(utcnow())
        if not isinstance(raw, dict) or not raw:
            raise BrowserPageError(400, "Rapport de page invalide.")
        try:
            if set(raw) == {"page"}:
                page = clean_page(raw["page"])
                return Report(page.url, page.title, False, page, now, stamp)
            if set(raw) <= {"excluded", "url", "title"} and raw.get("excluded") is True:
                title = raw.get("title", "")
                if not isinstance(title, str):
                    raise BrowserPageError(400, "title : texte attendu")
                return Report(
                    clean_url(raw.get("url")), title[:TITLE_MAX], True, None, now, stamp
                )
        except PageError as exc:
            raise BrowserPageError(400, exc.message) from exc
        raise BrowserPageError(
            400, "Rapport de page invalide : « page », ou « excluded » avec l'adresse."
        )

    def _live(self) -> Report | None:
        with self._lock:
            report = self._report
            if report is not None and self._clock() - report.at > TTL_S:
                self._report = report = None
        return report

    def latest(self) -> PageContext | None:
        """The page to attach, or None (nothing reported, unticked, or too old)."""
        report = self._live()
        return None if report is None or report.excluded else report.page

    def meta(self) -> dict[str, Any]:
        report = self._live()
        if report is None:
            return {"available": False}
        parts = urlsplit(report.url)
        return {
            "available": True,
            "excluded": report.excluded,
            "url": report.url,
            "origin": f"{parts.scheme}://{parts.netloc}",
            "title": report.title,
            "captured_at": report.captured_at,
        }
