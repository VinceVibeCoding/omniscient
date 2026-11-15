# Omnigroup pour Chrome et Edge

Un panneau latéral pour discuter avec votre démon Omnigroup local (Claude Code par défaut, ou
le fournisseur IA de votre choix), avec la page sur laquelle vous êtes comme contexte : un bug
qui s'affiche, une erreur de console, une requête qui échoue… sans capture d'écran.

Compatibilité : **Chrome ou Edge 116+** (Windows, macOS, Linux). Le démon Omnigroup doit tourner
sur la même machine (`omniscient group serve`, ou démarré par le widget).

## Installer (en attendant la publication dans les boutiques)

1. Construire : `cd extension && npm ci && npm run build` (ou télécharger l'artefact
   `omnigroup-extension` de la CI).
2. `chrome://extensions` (ou `edge://extensions`) › activer le **mode développeur** ›
   **Charger l'extension non empaquetée** › choisir le dossier `extension/dist`.
3. Cliquer l'icône Omnigroup : le panneau s'ouvre. **Demander un code** : il s'affiche sur le
   bureau Windows, comme pour le widget. Le taper, puis **Coupler**.

## Ce qui est lu, et quand

Rien n'est lu tant que vous n'avez pas **autorisé le site** (bouton dans le panneau, un site à
la fois, retirable à tout moment). L'icône affiche **ON** sur les onglets d'un site partagé.
Pour un site autorisé, et seulement quand vous envoyez une question avec « Joindre cette page »
coché :

- l'adresse (sans paramètres ni ancre), le titre, le texte visible, votre sélection ;
- les dernières erreurs de console (après un rechargement de la page qui suit l'autorisation) ;
- les requêtes en échec (méthode, adresse sans paramètres, statut).

Jamais : les valeurs des champs (donc les mots de passe), les cookies, les en-têtes, les
paramètres d'URL. Les secrets reconnus sont masqués par le démon. Les pages servies sur
`127.0.0.1` ne sont jamais partagées (l'extension a besoin de cette adresse pour parler au
démon, ce qui ne vaut pas accord) : utilisez `http://localhost:<port>`.

## Sécurité

- **Le texte d'une page n'est pas fiable** : il peut contenir des instructions écrites pour
  manipuler une IA. Il est donc transmis dans un bloc marqué « non fiable », et une
  conversation qui contient une page tourne **sans aucun outil** (Claude Code est lancé avec
  `--tools ""`) : elle peut expliquer, jamais agir.
- **Le démon est vérifié** avant tout envoi du jeton (preuve HMAC, comme le widget).
- **L'identifiant de l'extension est épinglé** par la clé publique du manifeste : le démon
  refuse toute autre extension. Pour une autre build (boutique, fork), ajoutez son ID avec
  `OMNIGROUP_EXTENSION_IDS`.
- Le jeton de couplage est gardé dans le stockage local de l'extension.

## Développer

```
npm ci
npm run typecheck && npm test && npm run build
# bout en bout (démon de test, faux fournisseur, Chromium de test) :
uv run --with playwright==1.64.1 python -m playwright install chromium
uv run --with playwright==1.64.1 python extension/e2e/run.py
```
