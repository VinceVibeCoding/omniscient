# Omnigroup pour Chrome et Edge

**Omnigroup, c'est le widget.** Cette extension est son capteur dans le navigateur : elle dit au
widget quelle page vous regardez, pour qu'il puisse la joindre à vos questions (un bug à
l'écran, une erreur de console, une requête qui échoue) sans capture d'écran. Les questions se
posent dans le **widget**, onglet Chat, case « Joindre la page du navigateur ».

Compatibilité : **Chrome ou Edge 116+** (Windows, macOS, Linux). Le démon Omnigroup tourne sur
la même machine (démarré par le widget, ou `omniscient group serve`).

## Installer (en attendant la publication dans les boutiques)

1. Construire : `cd extension && npm ci && npm run build` (ou l'artefact `omnigroup-extension`
   de la CI).
2. `chrome://extensions` (ou `edge://extensions`) › **mode développeur** › **Charger l'extension
   non empaquetée** › le dossier `extension/dist`. Chrome indique que l'extension peut « lire
   et modifier vos données sur tous les sites » : c'est ce qui lui permet de voir la page en cours.
3. Cliquer l'icône Omnigroup › **Demander un code** (il s'affiche sur le bureau Windows, comme
   pour le widget) › le taper › **Coupler**.

## Ce qui est lu, et quand

Par défaut, **toute page web** peut être jointe : l'icône affiche **ON**. Pour garder une page
pour vous, ouvrez le popup et **décochez « Joindre cette page »** : cela vaut pour cette page tant
que vous y êtes (une nouvelle page repart cochée), et le widget l'affiche comme non jointe.

À chaque changement de page, d'onglet, de sélection ou d'erreur, l'extension transmet au démon
**local** : l'adresse (sans paramètres ni ancre), le titre, le texte visible, votre sélection,
un **plan de la page** (titres, boutons, liens, champs, avec leur position à l'écran : « visible, en
haut à droite »), les dernières erreurs de console et les requêtes en échec. Le démon garde **seulement la dernière
page, en mémoire**, jamais sur disque, oubliée après 15 minutes. Le widget n'en voit que le titre
et l'adresse. **Rien ne part vers une IA tant que vous n'envoyez pas une question** avec la case
cochée dans le widget.

Jamais lus : les valeurs des champs (donc les mots de passe), les cookies, les en-têtes, les
paramètres d'URL. Les secrets reconnus sont masqués par le démon. Les pages du démon lui-même ne
sont jamais jointes.

## Sécurité

- **Le texte d'une page n'est pas fiable** : il peut contenir des instructions écrites pour
  manipuler une IA. Il est transmis dans un bloc marqué « non fiable », et une conversation qui
  contient une page tourne **sans aucun outil** (Claude Code est lancé avec `--tools ""`) : elle
  peut expliquer, jamais agir.
- **Le démon est vérifié** avant tout envoi du jeton (preuve HMAC, comme le widget).
- **L'identifiant de l'extension est épinglé** par la clé publique du manifeste : le démon refuse
  toute autre extension. Pour une autre build (boutique, fork), ajoutez son ID avec
  `OMNIGROUP_EXTENSION_IDS`.

## Développer

```
npm ci
npm run typecheck && npm test && npm run build
# bout en bout (démon de test, faux fournisseur, page de test, Chromium de test) :
uv run --with playwright==1.64.1 python -m playwright install chromium
uv run --with playwright==1.64.1 python extension/e2e/run.py
```
