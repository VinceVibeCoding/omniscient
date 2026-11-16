# Extensions

Omniscient n'est pas un produit fermé. Il te manque une commande, un thème, un workflow ou un
fournisseur prêt à l'emploi ? Demande-le à Omniscient : il le construit lui-même, tu tapes
`/reload` dans le chat du widget et tu continues. Si d'autres en ont l'usage, partage-le.

Une extension est un **dossier de données** (jamais du code) : `<dossier Omniscient>/extensions/<id>/`.

## Construire une extension en le demandant à l'IA

1. `omniscient ext init` écrit le guide `extensions/README.md` (pour toi et pour Claude Code).
2. Ouvre un chat du widget (ou Claude Code) sur le dossier Omniscient et décris ce que tu veux :
   « fais-moi une commande /resume qui résume la page en N points ».
3. L'IA écrit `extensions/<id>/extension.json` (et au besoin `README.md`, `LICENSE`), rien d'autre.
4. Tape `/reload` dans le chat du widget. Une erreur de format est affichée en français ;
   `omniscient ext validate` donne le même verdict dans le terminal.

Autres commandes : `omniscient ext list`, `new <id>`, `export <id> [--out f.zip]`,
`install <dossier ou https://github.com/auteur/depot> [--path sous/dossier] [--write] [--force]`,
`remove <id> --write`.

## Le manifeste `extension.json` (schema 1)

```json
{"schema": 1, "id": "resume-page", "name": "Résumer la page", "description": "…", "version": "1.0.0",
 "commands": [{"name": "resume", "title": "Résumer", "prompt": "Résume la page en {n} points.",
               "args": [{"name": "n", "default": "5"}], "attach_page": true}],
 "themes": [{"id": "ocean", "label": "Océan", "colors": {"--background": "#0b1d2a"}}],
 "workflows": [{"name": "review", "title": "Relecture", "needs_project": true,
                "steps": [{"prompt": "Relis les changements."}, {"prompt": "Liste les risques."}]}],
 "provider_presets": [{"id": "ollama-llama", "label": "Ollama", "kind": "openai-compatible",
                       "base_url": "http://127.0.0.1:11434/v1", "model": "llama3"}]}
```

| Champ | Règle |
|---|---|
| `id` | `[a-z0-9][a-z0-9-]{0,39}`, identique au nom du dossier |
| `version` | `1.0.0` |
| commande / workflow `name` | `[a-z][a-z0-9-]{0,29}`, unique parmi toutes les extensions, hors `reload`, `extensions`, `help` |
| `prompt` | 2000 caractères au plus ; seuls les `{arg}` déclarés sont permis, `{{` et `}}` pour une accolade littérale |
| `args` | 5 au plus ; l'utilisateur les tape dans l'ordre : `/resume 7` ; sans `default`, l'argument est requis |
| limites | 20 commandes, 10 thèmes, 10 workflows (8 étapes), 10 préréglages ; `default` 200 caractères |
| `colors` | variables CSS du widget autorisées : `--accent`, `--background`, `--border`, `--error`, `--foreground`, `--muted`, `--primary`, `--raised`, `--ring`, `--secondary`, `--success`, `--surface`, `--warning` ; valeurs `#rgb`, `#rrggbb`, `#rrggbbaa`, `rgb()` ou `rgba()` |
| `provider_presets` | `kind` parmi `openai`, `gemini`, `anthropic`, `openai-compatible` ; `base_url` pour ce dernier seulement |

Fichiers permis dans le dossier : `extension.json` (64 Ko au plus), `README.md`, `LICENSE`. Tout
autre fichier ou lien symbolique rend l'extension invalide : elle n'est pas chargée.

## Sécurité

- **Déclaratif seulement.** Aucun code n'est exécuté, importé ni téléchargé depuis une extension.
- **Revalidée à chaque chargement**, même écrite par une IA : clés inconnues refusées, longueurs bornées.
- **Listes d'autorisation.** Un thème ne touche que des couleurs ; jamais d'`url()` ni de `var()`.
- **Pas de privilège.** Une commande produit seulement le texte de ton propre message, envoyé par
  les routes de chat habituelles : une extension ne choisit ni les outils ni le fournisseur.
- **Les préréglages ne sont jamais des clés** : ils préremplissent le formulaire d'un fournisseur ;
  l'adresse est contrôlée à l'enregistrement, comme pour tout fournisseur.
- **Aperçu avant installation.** `ext install` montre tout (prompts, étapes, thèmes, fichiers) et
  n'installe qu'avec `--write`. Les sources git sont limitées à `https://github.com/...`, clonées
  sans hooks, sans rien exécuter ; seuls les trois fichiers permis sont copiés.

Routes du démon (jeton widget) : `GET /extensions`, `POST /extensions/reload`,
`PUT /extensions/{id}` (`{"enabled": bool}`), `DELETE /extensions/{id}`, `POST /extensions/expand`
(`{"command", "args"}`), plus l'événement SSE `extensions`.
