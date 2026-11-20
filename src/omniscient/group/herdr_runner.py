"""Run the `herdr` CLI (the optional terminal multiplexer) and turn its failures into one
error type. Control commands print a JSON envelope on stdout; server errors print
{"id": ..., "error": {...}} on stderr with exit status 1.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

HERDR_BIN = "herdr"
RUNNER_TIMEOUT_S = 60


class HerdrError(Exception):
    """herdr is missing, refused a command, or answered with an unexpected shape.

    `unavailable` marks the expected "herdr is not installed / not running" cases, which
    are not worth a traceback (herdr is optional).
    """

    def __init__(self, message: str, *, unavailable: bool = False) -> None:
        super().__init__(message)
        self.unavailable = unavailable


def _error_message(stderr: str) -> str:
    """The `.error.message` of herdr's JSON error, or the raw stderr."""
    text = stderr.strip()
    try:
        message = json.loads(text)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return text or "erreur inconnue"
    return str(message)


def default_runner(args: Sequence[str]) -> str:
    """Run `herdr <args>` and return stdout; any failure becomes a HerdrError."""
    try:
        proc = subprocess.run(
            [HERDR_BIN, *args],
            capture_output=True,
            text=True,
            timeout=RUNNER_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HerdrError(
            "herdr est introuvable dans le PATH", unavailable=True
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr {' '.join(args[:2])} : délai dépassé") from exc
    except OSError as exc:
        raise HerdrError(f"herdr n'a pas pu être lancé : {exc}") from exc
    if proc.returncode != 0:
        message = _error_message(proc.stderr)
        raise HerdrError(
            f"herdr {' '.join(args[:2])} : {message}",
            unavailable="no herdr server is running" in message,
        )
    return proc.stdout
