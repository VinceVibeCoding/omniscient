"""The owner's verdict on an idea note: the one write shared by the studio screens."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter

OWNER_VERDICTS = ("pursue", "reshape", "drop")


def _idea_path(vault: Path, stem: str) -> Path:
    ideas_dir = (vault / "ideas").resolve()
    path = (ideas_dir / f"{stem}.md").resolve()
    if path.parent != ideas_dir or not path.is_file():
        raise ValueError(f"unknown idea: {stem!r}")
    return path


def _update_meta(path: Path, **fields: Any) -> None:
    post = frontmatter.load(path)
    for key, value in fields.items():
        post[key] = value
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")


def apply_owner_verdict(vault: Path, stem: str, verdict: str) -> Path:
    """Record the owner's verdict. Drop ends the idea; pursue bypasses the threshold."""
    if verdict not in OWNER_VERDICTS:
        raise ValueError(f"verdict must be one of {OWNER_VERDICTS}")
    path = _idea_path(vault, stem)
    fields: dict[str, Any] = {"owner_verdict": verdict}
    if verdict == "drop":
        fields["status"] = "dropped"
    _update_meta(path, **fields)
    return path
