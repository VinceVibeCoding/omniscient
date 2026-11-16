"""Sharing: export an extension to a zip, preview and install one from a folder or git.

Nothing from the source is executed or imported. A git source is cloned shallowly into a
temp folder (hooks disabled, https://github.com only); only the allowed files are read,
validated and copied. Installing always starts with a preview; the copy needs `write=True`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from omniscient.group.ext_schema import Extension, ExtensionError
from omniscient.group.extensions import load_folder

GITHUB_URL = re.compile(
    r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}?(?:\.git)?/?$"
)
SUBPATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
CLONE_TIMEOUT_S = 60
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
GitFetch = Callable[[str, Path], None]


def git_clone(url: str, dest: Path) -> None:
    """A shallow, hook-less clone of a public https GitHub repository (nothing runs)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    cmd = [
        "git", "-c", f"core.hooksPath={os.devnull}", "-c", "core.symlinks=false",
        "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
        "clone", "--depth", "1", "--no-tags", "--single-branch", "--", url, str(dest),
    ]  # fmt: skip
    try:
        done = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLONE_TIMEOUT_S,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExtensionError(
            "git est introuvable : installe git ou utilise un dossier local."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtensionError(
            f"Le téléchargement dépasse {CLONE_TIMEOUT_S} s : abandon."
        ) from exc
    if done.returncode != 0:
        raise ExtensionError(
            "Impossible de cloner ce dépôt (adresse, droits ou réseau)."
        )


@dataclass(frozen=True)
class Source:
    extension: Extension
    folder: Path
    ignored: tuple[str, ...]  # files in the source that will NOT be copied


def check_github_url(url: str) -> str:
    if not GITHUB_URL.match(url):
        raise ExtensionError(
            "Seules les adresses https://github.com/<auteur>/<dépôt> sont acceptées."
        )
    return url


def _subfolder(base: Path, subpath: str | None) -> Path:
    if not subpath:
        return base
    parts = Path(subpath).parts
    if (
        Path(subpath).is_absolute()
        or not parts
        or not all(SUBPATH_PART.match(p) and p not in (".", "..") for p in parts)
    ):
        raise ExtensionError("--path : sous-dossier relatif simple attendu.")
    target = base.joinpath(*parts)
    if any(base.joinpath(*parts[: i + 1]).is_symlink() for i in range(len(parts))):
        raise ExtensionError("--path : lien symbolique refusé.")
    return target


@contextmanager
def open_source(
    source: str, subpath: str | None = None, git_fetch: GitFetch = git_clone
) -> Iterator[Source]:
    """The validated source (a local folder, or a temp clone removed afterwards)."""
    if source.startswith(("https://", "http://", "git@", "ssh://", "git://")):
        url = check_github_url(source)
        with tempfile.TemporaryDirectory(prefix="omniscient-ext-") as tmp:
            clone = Path(tmp) / "repo"
            git_fetch(url, clone)
            yield _read(_subfolder(clone, subpath))
        return
    if subpath:
        raise ExtensionError("--path ne s'utilise qu'avec une adresse git.")
    yield _read(Path(source).expanduser())


def _read(folder: Path) -> Source:
    ext = load_folder(folder, strict=False, check_name=False)
    names = {name for name, _ in ext.files}
    ignored = tuple(sorted(p.name for p in folder.iterdir() if p.name not in names))
    return Source(ext, folder, ignored)


def install(source: Source, root: Path, *, force: bool = False) -> Path:
    """Copy the allowed files to `<root>/<id>` (refuses an existing id without `force`)."""
    target = root / source.extension.id
    if os.path.lexists(target) and not force:
        raise ExtensionError(
            f"L'extension « {source.extension.id} » existe déjà (--force pour la remplacer)."
        )
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=root))
    try:
        for name, _ in source.extension.files:
            shutil.copyfile(source.folder / name, staging / name, follow_symlinks=False)
        if os.path.lexists(target):
            if target.is_symlink() or not target.is_dir():
                raise ExtensionError(
                    "Remplacement refusé : la cible n'est pas un dossier ordinaire."
                )
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def export_zip(folder: Path, out: Path) -> Path:
    """A deterministic zip (sorted names, fixed timestamps) of the allowed files only."""
    ext = load_folder(folder)
    tmp = out.with_suffix(out.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(n for n, _ in ext.files):
            info = zipfile.ZipInfo(f"{ext.id}/{name}", ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, (folder / name).read_bytes())
    os.replace(tmp, out)
    return out
