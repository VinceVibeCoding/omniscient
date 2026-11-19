"""Console output that never crashes on the user's code page.

On Windows a piped Python process encodes stdout with the ANSI code page (cp1252, cp1250,
cp932...): the check marks and arrows of our messages are not in it, and the default
`strict` error handler turns a status line into a traceback. `lossless_streams` keeps the
user's encoding (so the console shows what it can) but replaces what it cannot encode.
"""

from __future__ import annotations

import sys
from typing import Any


def lossless_streams(*streams: Any) -> None:
    """Switch the given text streams (default: stdout and stderr) to errors="replace"."""
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(
            stream, "reconfigure", None
        )  # None under pythonw / pytest
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                continue  # a closed or exotic stream: nothing to protect
