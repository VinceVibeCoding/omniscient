"""Shared helpers for the extension tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from omniscient.group.ext_guide import EXAMPLE_COMMAND

BASE: dict[str, Any] = {
    "schema": 1,
    "id": "demo",
    "name": "Démo",
    "description": "Une extension de test.",
    "version": "1.0.0",
}


def manifest(**extra: Any) -> dict[str, Any]:
    return {**copy.deepcopy(BASE), **extra}


def command(name: str = "resume", prompt: str = "Résume en {n}.", **extra: Any) -> dict:
    return {
        "name": name,
        "title": "T",
        "prompt": prompt,
        "args": [{"name": "n", "default": "5"}],
        **extra,
    }


def write_ext(
    root: Path, data: dict[str, Any] | None = None, folder: str | None = None
) -> Path:
    data = data if data is not None else copy.deepcopy(EXAMPLE_COMMAND)
    path = root / (folder or data["id"])
    path.mkdir(parents=True, exist_ok=True)
    (path / "extension.json").write_text(json.dumps(data), encoding="utf-8")
    return path
