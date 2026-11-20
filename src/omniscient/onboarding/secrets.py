"""Read/update <home>/.env (chmod 600) without ever echoing a value.

Values are written double-quoted (see omniscient.envfile), through a private temp file
in the same folder that replaces .env atomically: a crash never leaves a half-written
or world-readable secrets file.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

from omniscient.envfile import KEY_RE, parse_env, quote_value
from omniscient.group.credentials import replace_file, restrict_to_current_user

ENV_MODE = 0o600
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE pairs of an env file (quotes and escapes decoded); missing -> {}."""
    if not path.is_file():
        return {}
    return parse_env(path.read_text(encoding="utf-8"))


def _atomic_private_write(path: Path, text: str) -> None:
    """Write text to path via an O_EXCL 0600 temp file in the same dir + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)  # O_EXCL, 0600
    try:
        if hasattr(os, "fchmod"):  # POSIX; Windows uses an ACL below
            os.fchmod(fd, ENV_MODE)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        restrict_to_current_user(Path(tmp), is_dir=False)
        replace_file(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_env(path: Path, updates: Mapping[str, str]) -> None:
    """Replace/add keys (values double-quoted), keep every other line, mode 600."""
    for key, value in updates.items():
        if not NAME_RE.match(key) or "\n" in value or "\r" in value:
            raise ValueError(f"entrée .env invalide pour {key}")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        match = KEY_RE.match(line)
        key = match.group(1) if match and not line.lstrip().startswith("#") else None
        if key in pending:
            out.append(f"{key}={quote_value(pending.pop(key))}")
        else:
            out.append(line)
    out += [f"{key}={quote_value(value)}" for key, value in pending.items()]
    _atomic_private_write(path, "\n".join(out) + "\n")
