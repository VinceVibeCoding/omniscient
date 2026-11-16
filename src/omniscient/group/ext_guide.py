"""The extension guide written to `<home>/extensions/README.md`, and the `new` scaffold.

The guide is read by people AND by Claude Code sessions opened in the home. Its JSON
examples are checked by the tests: they must pass the validator.
"""

from __future__ import annotations

import json
from typing import Any

from omniscient.group.ext_schema import (
    BUILTIN_COMMANDS,
    MAX_ARG_DEFAULT,
    MAX_COMMANDS,
    MAX_PRESETS,
    MAX_STEPS,
    MAX_TEXT,
    MAX_THEMES,
    MAX_WORKFLOWS,
    THEME_VARS,
)

GUIDE_FILENAME = "README.md"

EXAMPLE_COMMAND = {
    "schema": 1,
    "id": "resume-page",
    "name": "Résumer la page",
    "description": "Une commande /resume qui résume la page ouverte.",
    "version": "1.0.0",
    "commands": [
        {
            "name": "resume",
            "title": "Résumer",
            "prompt": "Résume la page en {n} points, en français.",
            "args": [{"name": "n", "default": "5"}],
            "attach_page": True,
        }
    ],
}
EXAMPLE_THEME = {
    "schema": 1,
    "id": "ocean",
    "name": "Océan",
    "description": "Un thème bleu profond.",
    "version": "1.0.0",
    "themes": [
        {
            "id": "ocean",
            "label": "Océan",
            "colors": {
                "--background": "#0b1d2a",
                "--foreground": "#e6f1ff",
                "--primary": "rgb(56, 189, 248)",
            },
        }
    ],
}
EXAMPLE_WORKFLOW = {
    "schema": 1,
    "id": "review-two-steps",
    "name": "Relecture en 2 temps",
    "description": "Un workflow et un préréglage Ollama.",
    "version": "1.0.0",
    "workflows": [
        {
            "name": "review",
            "title": "Relecture en 2 temps",
            "needs_project": True,
            "steps": [
                {"prompt": "Relis les changements récents."},
                {"prompt": "Liste les risques."},
            ],
        }
    ],
    "provider_presets": [
        {
            "id": "ollama-llama",
            "label": "Ollama (llama)",
            "kind": "openai-compatible",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "llama3",
        }
    ],
}
EXAMPLES = (EXAMPLE_COMMAND, EXAMPLE_THEME, EXAMPLE_WORKFLOW)


def _block(manifest: dict[str, Any]) -> str:
    return "```json\n" + json.dumps(manifest, indent=2, ensure_ascii=False) + "\n```"


def build_guide() -> str:
    variables = ", ".join(f"`{v}`" for v in THEME_VARS)
    builtin = ", ".join(f"`{n}`" for n in sorted(BUILTIN_COMMANDS))
    return f"""# Construire une extension Omniscient

Une extension ajoute une commande, un thème, un workflow ou un préréglage de fournisseur au
widget, sans une ligne de code : ce sont des **données** (un fichier JSON). Demande-la à
l'IA dans un chat ouvert sur ce dossier, puis tape `/reload` dans le chat du widget.

## Règle pour Claude Code (et toute IA)

- Écris **seulement** `extension.json`, `README.md` et `LICENSE` dans `extensions/<id>/`.
  Tout autre fichier rend l'extension invalide (jamais chargée). Pas de code, pas de lien
  symbolique, pas d'URL à télécharger.
- Le dossier porte le même nom que `id` (`a-z`, `0-9`, tirets, 40 caractères au plus).
- Puis dis à l'utilisateur de taper `/reload` dans le chat du widget.
- Vérifie avec `omniscient ext validate <id>`.

## `extension.json` (schema 1)

Clés inconnues refusées. Obligatoires : `schema` (1), `id`, `name`, `description`,
`version` (`1.0.0`). Optionnelle : `author`. Listes : `commands` (au plus {MAX_COMMANDS}),
`themes` ({MAX_THEMES}), `workflows` ({MAX_WORKFLOWS}, {MAX_STEPS} étapes chacun),
`provider_presets` ({MAX_PRESETS}). Un texte (prompt, étape) fait {MAX_TEXT} caractères au plus.

- **commands** : `name` (`a-z`, `0-9`, tirets, commence par une lettre, 30 au plus, unique
  parmi toutes les extensions et différent de {builtin}), `title`, `prompt`, `args`
  (`name` + `default` facultatif de {MAX_ARG_DEFAULT} caractères au plus), `attach_page`.
  Le prompt n'utilise que des `{{arg}}` déclarés ; une accolade littérale s'écrit `{{{{` ou `}}}}`.
  L'utilisateur tape `/resume 7` : les arguments sont lus dans l'ordre (guillemets permis).
- **themes** : `id`, `label`, `colors` ; les clés viennent de cette liste : {variables}.
  Valeurs : `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb(r, g, b)` ou `rgba(r, g, b, a)`. Rien d'autre.
- **workflows** : `name`, `title`, `needs_project`, `steps` (une liste de `{{"prompt": "..."}}`).
- **provider_presets** : `id`, `label`, `kind` (openai, gemini, anthropic, openai-compatible),
  `base_url` (openai-compatible seulement), `model`. Un préréglage ne fait que **préremplir**
  le formulaire : jamais de clé, rien de créé tout seul.

## Exemples

### Une commande

{_block(EXAMPLE_COMMAND)}

### Un thème

{_block(EXAMPLE_THEME)}

### Un workflow et un préréglage

{_block(EXAMPLE_WORKFLOW)}

## Partager

`omniscient ext export <id>` crée un zip ; `omniscient ext install <dossier ou https://github.com/...>`
montre un aperçu complet, puis n'installe qu'avec `--write`.
"""


def scaffold_manifest(ext_id: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "id": ext_id,
        "name": ext_id,
        "description": "Mon extension : décris-la en une phrase.",
        "version": "0.1.0",
        "commands": [
            {
                "name": "bonjour",
                "title": "Dire bonjour",
                "prompt": "Dis bonjour à {nom}, en français.",
                "args": [{"name": "nom", "default": "toi"}],
                "attach_page": False,
            }
        ],
    }


def scaffold_readme(ext_id: str) -> str:
    return f"# {ext_id}\n\nExtension Omniscient. Tape `/reload` dans le chat du widget après chaque modification.\n"
