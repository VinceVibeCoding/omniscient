"""The `extension.json` schema (v1): frozen models and strict validation.

An extension is DECLARATIVE: data only, never code. Everything here treats the manifest as
untrusted input (an AI may have written it): unknown keys are refused, every text and
count has a cap, and the only values that can reach the widget are plain strings, booleans
and allowlisted theme colours.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from omniscient.group.providers import KINDS, MODEL

SCHEMA_VERSION = 1
EXTENSION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
NAME = re.compile(r"^[a-z][a-z0-9-]{0,29}$")  # command and workflow names
ARG_NAME = re.compile(r"^[a-z][a-z0-9_]{0,19}$")
THEME_ID = NAME
PRESET_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
VERSION = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")
BUILTIN_COMMANDS = frozenset({"reload", "extensions", "help"})

MAX_TEXT = 2000  # a prompt or a workflow step
MAX_ARG_DEFAULT = 200
MAX_COMMANDS = 20
MAX_ARGS = 5
MAX_THEMES = 10
MAX_WORKFLOWS = 10
MAX_STEPS = 8
MAX_PRESETS = 10
MAX_NAME = 60
MAX_DESCRIPTION = 300
MAX_AUTHOR = 80
MAX_URL = 200

# The widget's colour custom properties (widget/src/styles.css and themes.css); layout
# properties such as --radius, --gap and --osd-mono are deliberately not themable here.
THEME_VARS = (
    "--accent",
    "--background",
    "--border",
    "--error",
    "--foreground",
    "--muted",
    "--primary",
    "--raised",
    "--ring",
    "--secondary",
    "--success",
    "--surface",
    "--warning",
)
HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
RGB_COLOR = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*"
    r"(?:,\s*(0|1|0?\.\d{1,3}|1\.0{1,3})\s*)?\)$"
)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

TOP_KEYS = {
    "schema",
    "id",
    "name",
    "description",
    "version",
    "author",
    "commands",
    "themes",
    "workflows",
    "provider_presets",
}


class ExtensionError(Exception):
    """A refused extension or request; `message` is French and safe to show."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Arg:
    name: str
    default: str | None


@dataclass(frozen=True)
class Command:
    name: str
    title: str
    prompt: str
    args: tuple[Arg, ...]
    attach_page: bool


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    colors: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Workflow:
    name: str
    title: str
    needs_project: bool
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    kind: str
    base_url: str
    model: str


@dataclass(frozen=True)
class Extension:
    id: str
    name: str
    description: str
    version: str
    author: str
    commands: tuple[Command, ...]
    themes: tuple[Theme, ...]
    workflows: tuple[Workflow, ...]
    presets: tuple[Preset, ...]
    files: tuple[tuple[str, int], ...] = ()


# ---- primitives ------------------------------------------------------------------------


def _text(value: Any, where: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ExtensionError(f"{where} : un texte est attendu.")
    if (not empty and not value.strip()) or len(value) > limit:
        raise ExtensionError(f"{where} : texte de 1 à {limit} caractères attendu.")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ExtensionError(f"{where} : caractères de contrôle interdits.")
    return value


def _pattern(value: Any, rx: re.Pattern[str], where: str) -> str:
    if not isinstance(value, str) or not rx.match(value):
        raise ExtensionError(f"{where} : format invalide ({rx.pattern}).")
    return value


def _keys(obj: Any, allowed: set[str], required: set[str], where: str) -> dict:
    if not isinstance(obj, dict):
        raise ExtensionError(f"{where} : un objet est attendu.")
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise ExtensionError(f"{where} : clé inconnue « {unknown[0]} ».")
    missing = sorted(required - set(obj))
    if missing:
        raise ExtensionError(f"{where} : clé « {missing[0]} » manquante.")
    return obj


def _items(value: Any, limit: int, where: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise ExtensionError(f"{where} : une liste de {limit} éléments au plus.")
    return value


def _flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ExtensionError(f"{where} : vrai ou faux attendu.")
    return value


# ---- prompt templates ----------------------------------------------------------------


def template_parts(
    template: str, declared: set[str], where: str
) -> list[tuple[str, str | None]]:
    """(literal, placeholder) pairs; only declared `{arg}` placeholders are allowed."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as exc:
        raise ExtensionError(f"{where} : accolades mal formées ({exc}).") from exc
    parts: list[tuple[str, str | None]] = []
    for literal, field, spec, conversion in parsed:
        if field is not None and (spec or conversion or field not in declared):
            raise ExtensionError(
                f"{where} : paramètre « {{{field}}} » non déclaré dans args."
            )
        parts.append((literal, field))
    return parts


def _arg(raw: Any, where: str) -> Arg:
    obj = _keys(raw, {"name", "default"}, {"name"}, where)
    name = _pattern(obj["name"], ARG_NAME, f"{where}.name")
    default = obj.get("default")
    if default is not None:
        default = _text(default, f"{where}.default", MAX_ARG_DEFAULT, empty=True)
    return Arg(name, default)


def _command(raw: Any, where: str) -> Command:
    keys = {"name", "title", "prompt", "args", "attach_page"}
    obj = _keys(raw, keys, {"name", "title", "prompt"}, where)
    args = tuple(
        _arg(a, f"{where}.args[{i}]")
        for i, a in enumerate(_items(obj.get("args"), MAX_ARGS, f"{where}.args"))
    )
    if len({a.name for a in args}) != len(args):
        raise ExtensionError(f"{where}.args : noms d'arguments en double.")
    prompt = _text(obj["prompt"], f"{where}.prompt", MAX_TEXT)
    template_parts(prompt, {a.name for a in args}, f"{where}.prompt")
    return Command(
        _pattern(obj["name"], NAME, f"{where}.name"),
        _text(obj["title"], f"{where}.title", MAX_NAME),
        prompt,
        args,
        _flag(obj.get("attach_page", False), f"{where}.attach_page"),
    )


# ---- themes ------------------------------------------------------------------------


def valid_color(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    if HEX_COLOR.match(value):
        return True
    found = RGB_COLOR.match(value)
    return bool(found) and all(int(found.group(i)) <= 255 for i in (1, 2, 3))


def _theme(raw: Any, where: str) -> Theme:
    obj = _keys(raw, {"id", "label", "colors"}, {"id", "label", "colors"}, where)
    colors = obj["colors"]
    if not isinstance(colors, dict) or not 0 < len(colors) <= len(THEME_VARS):
        raise ExtensionError(f"{where}.colors : un objet de couleurs est attendu.")
    for key, value in colors.items():
        if key not in THEME_VARS:
            raise ExtensionError(f"{where}.colors : variable « {key} » non autorisée.")
        if not valid_color(value):
            raise ExtensionError(
                f"{where}.colors : couleur invalide pour {key} (#rgb, #rrggbb, #rrggbbaa, rgb() ou rgba())."
            )
    return Theme(
        _pattern(obj["id"], THEME_ID, f"{where}.id"),
        _text(obj["label"], f"{where}.label", MAX_NAME),
        tuple(sorted(colors.items())),
    )


# ---- workflows and presets ---------------------------------------------------------


def _workflow(raw: Any, where: str) -> Workflow:
    keys = {"name", "title", "needs_project", "steps"}
    obj = _keys(raw, keys, {"name", "title", "steps"}, where)
    steps = []
    for i, step in enumerate(_items(obj["steps"], MAX_STEPS, f"{where}.steps")):
        item = _keys(step, {"prompt"}, {"prompt"}, f"{where}.steps[{i}]")
        steps.append(_text(item["prompt"], f"{where}.steps[{i}].prompt", MAX_TEXT))
    if not steps:
        raise ExtensionError(f"{where}.steps : au moins une étape est attendue.")
    return Workflow(
        _pattern(obj["name"], NAME, f"{where}.name"),
        _text(obj["title"], f"{where}.title", MAX_NAME),
        _flag(obj.get("needs_project", False), f"{where}.needs_project"),
        tuple(steps),
    )


def check_url_syntax(url: str, where: str) -> str:
    """Syntax and scheme only (a preset prefills the form; saving does the full check)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError as exc:
        raise ExtensionError(f"{where} : adresse invalide.") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise ExtensionError(
            f"{where} : l'adresse doit commencer par https:// (ou http:// en local)."
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ExtensionError(f"{where} : ni identifiants, ni paramètres, ni ancre.")
    if parts.scheme == "http" and host.lower() not in LOOPBACK_HOSTS:
        raise ExtensionError(f"{where} : http:// n'est permis que vers cette machine.")
    return url.strip().rstrip("/")


def _preset(raw: Any, where: str) -> Preset:
    keys = {"id", "label", "kind", "base_url", "model"}
    obj = _keys(raw, keys, {"id", "label", "kind"}, where)
    kind = obj["kind"]
    if kind not in KINDS:
        raise ExtensionError(f"{where}.kind : type inconnu (parmi {', '.join(KINDS)}).")
    base = obj.get("base_url", "")
    if kind == "openai-compatible":
        base = check_url_syntax(
            _text(base, f"{where}.base_url", MAX_URL), f"{where}.base_url"
        )
    elif base != "":
        raise ExtensionError(f"{where}.base_url : réservé au type openai-compatible.")
    model = obj.get("model", "")
    if not isinstance(model, str) or (model != "" and not MODEL.match(model)):
        raise ExtensionError(f"{where}.model : nom de modèle invalide.")
    return Preset(
        _pattern(obj["id"], PRESET_ID, f"{where}.id"),
        _text(obj["label"], f"{where}.label", MAX_NAME),
        kind,
        base,
        model,
    )


# ---- the manifest ----------------------------------------------------------------------


def _unique(names: list[str], what: str) -> None:
    if len(set(names)) != len(names):
        raise ExtensionError(f"{what} en double dans l'extension.")


def parse_manifest(data: Any, folder_name: str | None = None) -> Extension:
    """The validated Extension; `folder_name`, when given, must equal the manifest id."""
    obj = _keys(
        data, TOP_KEYS, {"schema", "id", "name", "description", "version"}, "manifest"
    )
    if obj["schema"] != SCHEMA_VERSION or isinstance(obj["schema"], bool):
        raise ExtensionError(
            f"schema : seule la version {SCHEMA_VERSION} est prise en charge."
        )
    ext_id = _pattern(obj["id"], EXTENSION_ID, "id")
    if folder_name is not None and ext_id != folder_name:
        raise ExtensionError("id : doit être identique au nom du dossier.")
    author = obj.get("author", "")
    commands = tuple(
        _command(c, f"commands[{i}]")
        for i, c in enumerate(_items(obj.get("commands"), MAX_COMMANDS, "commands"))
    )
    themes = tuple(
        _theme(t, f"themes[{i}]")
        for i, t in enumerate(_items(obj.get("themes"), MAX_THEMES, "themes"))
    )
    workflows = tuple(
        _workflow(w, f"workflows[{i}]")
        for i, w in enumerate(_items(obj.get("workflows"), MAX_WORKFLOWS, "workflows"))
    )
    presets = tuple(
        _preset(p, f"provider_presets[{i}]")
        for i, p in enumerate(
            _items(obj.get("provider_presets"), MAX_PRESETS, "provider_presets")
        )
    )
    _unique(
        [c.name for c in commands] + [w.name for w in workflows],
        "Nom de commande ou de workflow",
    )
    _unique([t.id for t in themes], "Identifiant de thème")
    _unique([p.id for p in presets], "Identifiant de préréglage")
    return Extension(
        ext_id,
        _text(obj["name"], "name", MAX_NAME),
        _text(obj["description"], "description", MAX_DESCRIPTION),
        _pattern(obj["version"], VERSION, "version"),
        _text(author, "author", MAX_AUTHOR, empty=True),
        commands,
        themes,
        workflows,
        presets,
    )
