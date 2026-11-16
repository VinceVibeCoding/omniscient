"""The daemon's extension service: cached load, enable/disable list, safe removal.

`<state>/extensions.json` = {"disabled": [ids]} (0600, atomic write). The extensions
folder is `<home>/extensions` (visible to the user, not under `.omniscient/`).
"""

from __future__ import annotations

import json
import logging
import shutil
import stat
import threading
from pathlib import Path
from typing import Any

from omniscient.group.credentials import secure_dir, write_atomic
from omniscient.group.ext_schema import EXTENSION_ID, Extension, ExtensionError
from omniscient.group.extensions import Command, LoadResult, expand, load_all

log = logging.getLogger(__name__)

DISABLED_FILE = "extensions.json"
MAX_DISABLED = 500


def extensions_root(home_root: Path) -> Path:
    return home_root / "extensions"


def _arg_view(arg: Any) -> dict[str, Any]:
    return {"name": arg.name, "default": arg.default}


def extension_view(ext: Extension, enabled: bool) -> dict[str, Any]:
    """The JSON the widget gets: never a path, never a file content other than prompts."""
    return {
        "id": ext.id,
        "name": ext.name,
        "description": ext.description,
        "version": ext.version,
        "author": ext.author,
        "enabled": enabled,
        "commands": [
            {
                "name": c.name,
                "title": c.title,
                "args": [_arg_view(a) for a in c.args],
                "attach_page": c.attach_page,
            }
            for c in ext.commands
        ],
        "themes": [
            {"id": t.id, "label": t.label, "colors": dict(t.colors)} for t in ext.themes
        ],
        "workflows": [
            {
                "name": w.name,
                "title": w.title,
                "needs_project": w.needs_project,
                "steps": [{"prompt": s} for s in w.steps],
            }
            for w in ext.workflows
        ],
        "provider_presets": [
            {
                "id": p.id,
                "label": p.label,
                "kind": p.kind,
                "base_url": p.base_url,
                "model": p.model,
            }
            for p in ext.presets
        ],
    }


class ExtensionStore:
    def __init__(self, root: Path, state_dir: Path) -> None:
        self.root = root
        self.state_dir = state_dir
        self._lock = threading.Lock()
        self._loaded = LoadResult()
        self.reload()

    # ---- the disabled list ---------------------------------------------------------

    @property
    def disabled_path(self) -> Path:
        return self.state_dir / DISABLED_FILE

    def disabled(self) -> frozenset[str]:
        try:
            data = json.loads(self.disabled_path.read_text(encoding="utf-8"))
            ids = data["disabled"]
            if not isinstance(ids, list):
                raise TypeError("disabled must be a list")
            return frozenset(
                i for i in ids if isinstance(i, str) and EXTENSION_ID.match(i)
            )
        except FileNotFoundError:
            return frozenset()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning(
                "omnigroup: unreadable %s (%s): none disabled", DISABLED_FILE, exc
            )
            return frozenset()

    def _save_disabled(self, ids: frozenset[str]) -> None:
        secure_dir(self.state_dir)
        payload = {"disabled": sorted(ids)[:MAX_DISABLED]}
        write_atomic(self.disabled_path, json.dumps(payload, indent=2) + "\n")

    # ---- loading ---------------------------------------------------------------------

    def reload(self) -> LoadResult:
        result = load_all(self.root)
        with self._lock:
            self._loaded = result
        return result

    def snapshot(self) -> LoadResult:
        with self._lock:
            return self._loaded

    def view(self) -> dict[str, Any]:
        loaded, off = self.snapshot(), self.disabled()
        return {
            "extensions": [
                extension_view(e, e.id not in off) for e in loaded.extensions
            ],
            "errors": [{"id": e.id, "message": e.message} for e in loaded.errors],
        }

    # ---- changes -------------------------------------------------------------------

    def _known(self, ext_id: str) -> Extension:
        for ext in self.snapshot().extensions:
            if ext.id == ext_id:
                return ext
        raise ExtensionError("Extension inconnue.", 404)

    def set_enabled(self, ext_id: str, enabled: bool) -> None:
        self._known(ext_id)
        off = self.disabled()
        self._save_disabled(off - {ext_id} if enabled else off | {ext_id})

    def enable(self, ext_id: str) -> None:
        self.set_enabled(ext_id, True)

    def disable(self, ext_id: str) -> None:
        self.set_enabled(ext_id, False)

    def remove(self, ext_id: str) -> None:
        """Delete `<root>/<id>` only: a plain folder directly inside the root."""
        if not isinstance(ext_id, str) or not EXTENSION_ID.match(ext_id):
            raise ExtensionError("Identifiant d'extension invalide.", 400)
        target = self.root / ext_id
        try:
            info = target.lstat()
        except FileNotFoundError:
            raise ExtensionError("Extension inconnue.", 404) from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ExtensionError(
                "Suppression refusée : ce n'est pas un dossier ordinaire."
            )
        if target.resolve().parent != self.root.resolve():
            raise ExtensionError("Suppression refusée : dossier hors des extensions.")
        shutil.rmtree(target)
        self._save_disabled(self.disabled() - {ext_id})
        self.reload()

    # ---- commands ----------------------------------------------------------------

    def find_command(self, name: str) -> tuple[Extension, Command]:
        off = self.disabled()
        for ext in self.snapshot().extensions:
            if ext.id in off:
                continue
            for command in ext.commands:
                if command.name == name:
                    return ext, command
        raise ExtensionError("Commande inconnue ou extension désactivée.", 404)

    def expand(self, name: str, args_text: str) -> dict[str, Any]:
        _, command = self.find_command(name)
        return {"text": expand(command, args_text), "attach_page": command.attach_page}
