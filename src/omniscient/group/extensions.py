"""Omniscient extensions: declarative folders under `<home>/extensions/<id>/`.

An extension holds only `extension.json`, `README.md` and `LICENSE` (data, never code).
`load_all` reads every folder, validates it from scratch and NEVER raises: an invalid
extension becomes an error entry with a French message and is not loaded. Symlinks are
never followed. `expand` turns a command and its arguments into the text of the user's own
chat message: an extension gets no other privilege (no tools, no provider choice).
"""

from __future__ import annotations

import json
import os
import shlex
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from omniscient.group.ext_schema import (
    BUILTIN_COMMANDS,
    EXTENSION_ID,
    Arg,
    Command,
    Extension,
    ExtensionError,
    Preset,
    Theme,
    Workflow,
    parse_manifest,
    template_parts,
)

__all__ = [
    "Arg",
    "Command",
    "ExtError",
    "Extension",
    "ExtensionError",
    "LoadResult",
    "Preset",
    "Theme",
    "Workflow",
    "expand",
    "load_all",
    "load_folder",
]  # fmt: skip

MANIFEST = "extension.json"
ALLOWED_FILES = (MANIFEST, "LICENSE", "README.md")
MAX_FILE_BYTES = 64 * 1024
MAX_EXPANDED = 8000
MAX_ARGS_TEXT = 2000


@dataclass(frozen=True)
class ExtError:
    id: str
    message: str


@dataclass(frozen=True)
class LoadResult:
    extensions: tuple[Extension, ...] = ()
    errors: tuple[ExtError, ...] = ()


# ---- reading one folder --------------------------------------------------------------


def read_text_file(path: Path) -> str:
    """A small UTF-8 file, never through a symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ExtensionError(
            f"{path.name} : fichier illisible ou lien symbolique."
        ) from exc
    with os.fdopen(fd, "rb") as fh:
        raw = fh.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ExtensionError(f"{path.name} : plus de {MAX_FILE_BYTES // 1024} Ko.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtensionError(f"{path.name} : le fichier doit être en UTF-8.") from exc


def _list_files(folder: Path, *, strict: bool) -> tuple[tuple[str, int], ...]:
    """The allowed files with sizes. Strict: anything else (or a symlink) is refused."""
    found: list[tuple[str, int]] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        info = entry.lstat()
        allowed = entry.name in ALLOWED_FILES
        if stat.S_ISLNK(info.st_mode):
            raise ExtensionError(f"{entry.name} : les liens symboliques sont refusés.")
        if not allowed:
            if strict:
                raise ExtensionError(
                    f"{entry.name} : fichier non autorisé (seuls {', '.join(ALLOWED_FILES)})."
                )
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ExtensionError(f"{entry.name} : un fichier ordinaire est attendu.")
        found.append((entry.name, info.st_size))
    return tuple(found)


def load_folder(
    folder: Path, *, strict: bool = True, check_name: bool = True
) -> Extension:
    """The validated extension in `folder`; ExtensionError (French) otherwise.

    `strict=False` (installing from a git checkout) ignores files that are not allowed
    instead of refusing them; they are never read or copied. `check_name=False` skips
    the "id equals folder name" rule (the source folder of an install has any name).
    """
    if folder.is_symlink() or not folder.is_dir():
        raise ExtensionError("dossier introuvable ou lien symbolique.")
    files = _list_files(folder, strict=strict)
    if MANIFEST not in dict(files):
        raise ExtensionError(f"{MANIFEST} manquant.")
    for name, size in files:
        if size > MAX_FILE_BYTES:
            raise ExtensionError(f"{name} : plus de {MAX_FILE_BYTES // 1024} Ko.")
    try:
        data = json.loads(read_text_file(folder / MANIFEST))
    except json.JSONDecodeError as exc:
        raise ExtensionError(
            f"{MANIFEST} : JSON invalide ({exc.msg}, ligne {exc.lineno})."
        ) from exc
    for name, _ in files:  # README and LICENSE must at least be valid UTF-8
        if name != MANIFEST:
            read_text_file(folder / name)
    ext = parse_manifest(data, folder.name if check_name else None)
    return replace(ext, files=files)


# ---- all folders ---------------------------------------------------------------------


def _collisions(ext: Extension, taken: dict[str, str]) -> str | None:
    names = [c.name for c in ext.commands] + [w.name for w in ext.workflows]
    for name in names:
        if name in BUILTIN_COMMANDS:
            return f"« {name} » est une commande intégrée."
        if name in taken:
            return f"« {name} » est déjà utilisé par l'extension {taken[name]}."
    return None


def load_all(root: Path) -> LoadResult:
    """Every extension under `root` (sorted by id); invalid ones become errors."""
    extensions: list[Extension] = []
    errors: list[ExtError] = []
    taken: dict[str, str] = {}
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name) if root.is_dir() else []
    except OSError as exc:
        return LoadResult(
            (), (ExtError("", f"Dossier des extensions illisible : {exc.strerror}."),)
        )
    for entry in entries:
        name = entry.name
        if name.startswith(".") or (entry.is_file() and not entry.is_symlink()):
            continue  # temp folders of an install, and the root README
        if not EXTENSION_ID.match(name):
            errors.append(
                ExtError(name[:40], "Nom de dossier invalide (a-z, 0-9, tirets).")
            )
            continue
        try:
            ext = load_folder(entry)
            clash = _collisions(ext, taken)
            if clash:
                raise ExtensionError(clash)
        except (ExtensionError, OSError) as exc:
            message = (
                exc.message if isinstance(exc, ExtensionError) else str(exc.strerror)
            )
            errors.append(ExtError(name, message))
            continue
        taken.update(
            {
                n: ext.id
                for n in [c.name for c in ext.commands]
                + [w.name for w in ext.workflows]
            }
        )
        extensions.append(ext)
    return LoadResult(tuple(extensions), tuple(errors))


# ---- expansion -----------------------------------------------------------------------


def _bind(command: Command, args_text: str) -> dict[str, str]:
    if len(args_text) > MAX_ARGS_TEXT:
        raise ExtensionError(
            f"Arguments trop longs ({MAX_ARGS_TEXT} caractères au plus)."
        )
    try:
        tokens = shlex.split(args_text)
    except ValueError as exc:
        raise ExtensionError(f"Arguments mal formés : {exc}.") from exc
    if len(tokens) > len(command.args):
        raise ExtensionError(
            f"/{command.name} attend {len(command.args)} argument(s) au plus."
        )
    values: dict[str, str] = {}
    for index, arg in enumerate(command.args):
        if index < len(tokens):
            values[arg.name] = tokens[index]
        elif arg.default is not None:
            values[arg.name] = arg.default
        else:
            raise ExtensionError(
                f"/{command.name} : l'argument « {arg.name} » est requis."
            )
    return values


def expand(command: Command, args_text: str) -> str:
    """The prompt with the arguments substituted (declared placeholders only)."""
    values = _bind(command, args_text)
    parts = template_parts(command.prompt, {a.name for a in command.args}, command.name)
    text = "".join(lit + (values[field] if field else "") for lit, field in parts)
    if len(text) > MAX_EXPANDED:
        raise ExtensionError(f"Le texte obtenu dépasse {MAX_EXPANDED} caractères.")
    return text
