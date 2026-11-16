"""`omniscient ext …`: build, check, share and install declarative extensions.

Extensions are data folders in `<home>/extensions/<id>/` (see group/extensions.py).
Nothing is installed or removed without `--write`; installing shows a full preview first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from omniscient.group import ext_package as pkg
from omniscient.group.ext_guide import (
    GUIDE_FILENAME,
    build_guide,
    scaffold_manifest,
    scaffold_readme,
)
from omniscient.group.ext_schema import EXTENSION_ID, Extension, ExtensionError
from omniscient.group.ext_store import ExtensionStore, extensions_root
from omniscient.group.extensions import MANIFEST, load_all, load_folder
from omniscient.home import find_home

ext_app = typer.Typer(
    help="Extensions : commandes, thèmes, workflows et préréglages (des données, jamais du code).",
    no_args_is_help=True,
)
GitFetchHook = {"fetch": pkg.git_clone}  # replaced by tests: no network


def _root() -> Path:
    return extensions_root(find_home().root)


def _fail(message: str) -> typer.Exit:
    typer.echo(f"Erreur : {message}", err=True)
    return typer.Exit(code=1)


def _check_id(ext_id: str) -> str:
    if not EXTENSION_ID.match(ext_id):
        raise _fail("identifiant invalide (a-z, 0-9, tirets ; 40 caractères au plus).")
    return ext_id


@ext_app.command("list")
def list_cmd() -> None:
    """Liste les extensions installées et leurs erreurs."""
    home = find_home()
    store = ExtensionStore(extensions_root(home.root), home.state)
    view = store.view()
    for ext in view["extensions"]:
        state = "active" if ext["enabled"] else "désactivée"
        typer.echo(f"{ext['id']} {ext['version']} ({state}) : {ext['name']}")
    for err in view["errors"]:
        typer.echo(f"INVALIDE {err['id']} : {err['message']}")
    if not view["extensions"] and not view["errors"]:
        typer.echo("Aucune extension. Crée-en une : omniscient ext new <id>")


@ext_app.command("new")
def new_cmd(
    ext_id: Annotated[str, typer.Argument(help="Identifiant (a-z, 0-9, tirets).")],
) -> None:
    """Crée une extension d'exemple valide (manifeste + README)."""
    import json

    folder = _root() / _check_id(ext_id)
    if folder.exists() or folder.is_symlink():
        raise _fail(f"« {ext_id} » existe déjà.")
    folder.mkdir(parents=True)
    manifest = json.dumps(scaffold_manifest(ext_id), indent=2, ensure_ascii=False)
    (folder / MANIFEST).write_text(manifest + "\n", encoding="utf-8")
    (folder / "README.md").write_text(scaffold_readme(ext_id), encoding="utf-8")
    typer.echo(
        f"Extension créée : extensions/{ext_id}/. Modifie-la, puis tape /reload dans le widget."
    )


@ext_app.command("validate")
def validate_cmd(ext_id: Annotated[str | None, typer.Argument()] = None) -> None:
    """Vérifie une extension (ou toutes) avec les règles du démon."""
    root = _root()
    if ext_id is None:
        result = load_all(root)
        for ext in result.extensions:
            typer.echo(f"OK {ext.id}")
        for err in result.errors:
            typer.echo(f"INVALIDE {err.id} : {err.message}")
        if result.errors:
            raise typer.Exit(code=1)
        return
    try:
        load_folder(root / _check_id(ext_id))
    except ExtensionError as exc:
        raise _fail(f"{ext_id} : {exc.message}") from exc
    typer.echo(f"OK {ext_id}")


@ext_app.command("init")
def init_cmd() -> None:
    """Écrit le guide extensions/README.md (pour toi et pour Claude Code)."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    (root / GUIDE_FILENAME).write_text(build_guide(), encoding="utf-8")
    typer.echo("Guide écrit : extensions/README.md")


@ext_app.command("export")
def export_cmd(
    ext_id: Annotated[str, typer.Argument()],
    out: Annotated[
        Path | None, typer.Option("--out", help="Fichier .zip à écrire.")
    ] = None,
) -> None:
    """Exporte une extension en zip (seulement les fichiers autorisés)."""
    target = out or Path(f"{ext_id}.zip")
    try:
        path = pkg.export_zip(_root() / _check_id(ext_id), target)
    except ExtensionError as exc:
        raise _fail(f"{ext_id} : {exc.message}") from exc
    typer.echo(f"Zip écrit : {path}")


def render_preview(ext: Extension, ignored: tuple[str, ...]) -> list[str]:
    lines = [
        f"Extension : {ext.id} {ext.version}",
        f"Nom : {ext.name}",
        f"Description : {ext.description}",
    ]
    lines.append(f"Auteur : {ext.author or '(non indiqué)'}")
    for c in ext.commands:
        args = ", ".join(
            f"{a.name}={a.default!r}" if a.default is not None else a.name
            for a in c.args
        )
        lines.append(
            f"Commande /{c.name} ({c.title}) args [{args}] page jointe : {'oui' if c.attach_page else 'non'}"
        )
        lines.append(f"    prompt : {c.prompt}")
    for t in ext.themes:
        colors = ", ".join(f"{k}={v}" for k, v in t.colors)
        lines.append(f"Thème {t.id} ({t.label}) : {colors}")
    for w in ext.workflows:
        lines.append(
            f"Workflow /{w.name} ({w.title}) projet requis : {'oui' if w.needs_project else 'non'}"
        )
        lines.extend(f"    étape {i} : {s}" for i, s in enumerate(w.steps, 1))
    for p in ext.presets:
        lines.append(
            f"Préréglage {p.id} ({p.label}) : {p.kind} {p.base_url} {p.model} (préremplit seulement, aucune clé)"
        )
    lines.append("Fichiers copiés : " + ", ".join(f"{n} ({s} o)" for n, s in ext.files))
    if ignored:
        lines.append("Fichiers ignorés (jamais copiés) : " + ", ".join(ignored))
    return lines


@ext_app.command("install")
def install_cmd(
    source: Annotated[
        str,
        typer.Argument(help="Dossier local ou https://github.com/<auteur>/<dépôt>."),
    ],
    path: Annotated[
        str | None, typer.Option("--path", help="Sous-dossier du dépôt.")
    ] = None,
    write: Annotated[
        bool, typer.Option("--write", help="Installer pour de bon.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Remplacer une extension existante.")
    ] = False,
) -> None:
    """Aperçu complet d'une extension, puis installation avec --write."""
    try:
        with pkg.open_source(source, path, GitFetchHook["fetch"]) as src:
            for line in render_preview(src.extension, src.ignored):
                typer.echo(line)
            if not write:
                typer.echo(
                    "\nAperçu seulement : rien n'est installé. Relance avec --write pour confirmer."
                )
                return
            target = pkg.install(src, _root(), force=force)
    except ExtensionError as exc:
        raise _fail(exc.message) from exc
    typer.echo(f"\nInstallée : extensions/{target.name}/. Tape /reload dans le widget.")


@ext_app.command("remove")
def remove_cmd(
    ext_id: Annotated[str, typer.Argument()],
    write: Annotated[
        bool, typer.Option("--write", help="Supprimer pour de bon.")
    ] = False,
) -> None:
    """Supprime une extension (aperçu sans --write)."""
    if not write:
        typer.echo(
            f"Aperçu : extensions/{_check_id(ext_id)}/ serait supprimée. Relance avec --write."
        )
        return
    home = find_home()
    try:
        ExtensionStore(extensions_root(home.root), home.state).remove(ext_id)
    except ExtensionError as exc:
        raise _fail(exc.message) from exc
    typer.echo(f"Extension supprimée : {ext_id}. Tape /reload dans le widget.")


def register(app: typer.Typer) -> None:
    app.add_typer(ext_app, name="ext")
