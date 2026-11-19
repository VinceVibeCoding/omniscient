# Installer Omniscient sur Windows

Une seule commande, à coller dans PowerShell (menu Démarrer, taper *PowerShell*) :

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.ps1 | iex"
```

Prérequis : Windows 10 ou 11 et une connexion Internet. Rien d'autre : pas de droits
administrateur, pas de git, pas de Python (uv le télécharge). Claude Code est facultatif : il ne
sert que pour les conversations de code.

Relancer la même commande **met tout à jour** (le script est idempotent).

## Ce que fait le script, étape par étape

Le texte est celui de [`install.ps1`](../install.ps1) : lis-le avant de l'exécuter si tu veux.

1. **uv.** Cherche `uv`. Sinon : `winget install astral-sh.uv`, sinon l'installeur officiel
   `https://astral.sh/uv/install.ps1` (le seul script téléchargé puis exécuté). Rafraîchit le
   `PATH` de la session, avec `%USERPROFILE%\.local\bin`.
2. **Moteur, sans git.** Lit la dernière version publiée sur GitHub
   (`api.github.com/repos/VinceVibeCoding/omniscient/releases/latest`), télécharge la roue
   `omniscient-<version>-py3-none-any.whl` et `SHA256SUMS` en HTTPS, **vérifie le SHA-256**, puis
   `uv tool install --force <roue>`. Si un démon tourne déjà, il est arrêté avant la mise à jour.
   `uv tool update-shell` ajoute le dossier des outils au `PATH` de ton utilisateur.
3. **Démon.** `omniscient group autostart install --write` crée une tâche planifiée « Omnigroup »
   à l'ouverture de ta session (sans droits administrateur, sans fenêtre), puis le démon est lancé
   tout de suite et le script attend qu'il réponde sur `http://127.0.0.1:7341` (local seulement).
4. **Hooks et widget.** `omniscient group setup --write` écrit les hooks et la statusLine dans
   `~/.claude/settings.json` (une sauvegarde est faite avant ; les autres réglages sont gardés),
   télécharge l'installeur `Omnigroup_<version>_x64-setup.exe` de la même version, vérifie son
   SHA-256 (et sa provenance si `gh` est installé), puis le lance en mode silencieux (`/S`),
   pour ton utilisateur seulement.
5. **État.** Affiche `omniscient group status`, puis « Et maintenant » : ouvre Omnigroup,
   *Réglages › Demander un code*, tape le code à 6 chiffres affiché sur ton bureau.

En cas d'échec, le script s'arrête avec un message précis (étape, cause) et ne laisse rien de
dangereux : relance-le après correction.

## Ce qu'il écrit, et où

| Quoi | Où | Comment l'enlever |
|---|---|---|
| uv (si absent) | géré par winget, ou `%USERPROFILE%\.local\bin` | `winget uninstall astral-sh.uv`, ou supprimer ce dossier |
| Python 3.12+ (si absent) | dossier de données de uv (`uv python dir`) | `uv python uninstall 3.12` |
| Moteur | dossier d'outils de uv (`uv tool dir`), commande `omniscient.exe` dans `%USERPROFILE%\.local\bin` | `uv tool uninstall omniscient` |
| `PATH` utilisateur | variable d'environnement de ton utilisateur (par `uv tool update-shell`) | Paramètres Windows › Variables d'environnement |
| Démarrage du démon | tâche planifiée « Omnigroup » (utilisateur courant) | `omniscient group autostart remove` |
| Hooks Claude Code | `%USERPROFILE%\.claude\settings.json` (+ copie de sauvegarde à côté) | `omniscient group hooks uninstall --write` |
| Widget | `%LOCALAPPDATA%\Omnigroup\` et entrée du menu Démarrer | Paramètres › Applications › Omnigroup › Désinstaller |
| État du démon (jeton des hooks, `group.db`) | `%USERPROFILE%\.omniscient\` | supprimer le dossier |
| Jeton de couplage du widget | Gestionnaire d'identifiants Windows | `omniscient group pair --revoke` oublie les widgets couplés ; le jeton local se supprime à la main dans le Gestionnaire d'identifiants |
| Fichiers temporaires | `%TEMP%\omniscient-install-*`, effacés à la fin | rien à faire |

Le script n'écrit jamais ailleurs que dans ton profil, ne demande pas l'élévation, ne
change pas la politique d'exécution de ta machine (`-ExecutionPolicy ByPass` ne vaut que pour ce
processus) et n'affiche ni ne stocke aucun secret.

## Tout désinstaller

Dans PowerShell, dans cet ordre :

```powershell
omniscient group autostart remove          # la tâche planifiée
omniscient group hooks uninstall --write   # nos hooks dans ~/.claude/settings.json (le reste est gardé)
omniscient group pair --revoke             # oublie les widgets couplés
uv tool uninstall omniscient               # le moteur
```

Puis le widget : *Paramètres Windows › Applications › Omnigroup › Désinstaller*. Enfin, si tu le
veux, supprime `%USERPROFILE%\.omniscient` (état et jeton du démon) et, si tu as créé un dossier de
travail avec `omniscient init`, ce dossier-là.

## Dépannage

- **SmartScreen « Windows a protégé votre ordinateur ».** Le widget n'est pas encore signé par un
  éditeur reconnu. Un fichier téléchargé par le script (PowerShell ne pose pas la « marque du
  Web ») ne déclenche normalement rien ; si l'écran apparaît quand même, *Informations
  complémentaires › Exécuter quand même*. Vérifie l'empreinte avec `SHA256SUMS` de la release.
- **Antivirus ou « Contrôle d'application ».** Un antivirus peut bloquer `omnigroup.exe` ou la
  tâche planifiée. Ajoute une exception pour `%LOCALAPPDATA%\Omnigroup` et pour le dossier de
  `uv tool dir`, puis relance la commande.
- **Pas de winget.** Normal sur Windows 10 ancien ou en entreprise : le script bascule tout seul
  sur l'installeur officiel de uv. Si tout est bloqué, installe uv à la main
  (<https://docs.astral.sh/uv/>) et relance la commande.
- **Proxy d'entreprise.** Définis `HTTPS_PROXY` (et `HTTP_PROXY`) avant de lancer la commande, ou
  configure le proxy système. Le démon, lui, parle seulement à `127.0.0.1` sans proxy.
- **« Impossible de lire la dernière version sur GitHub ».** Pas d'Internet, proxy, ou limite
  d'appels de l'API GitHub : attends quelques minutes ou change de réseau.
- **« ne contient pas encore le moteur ».** La dernière version publiée précède l'installation en
  une commande : utilise l'installation manuelle du README.
- **`omniscient` introuvable après l'installation.** Ferme et rouvre PowerShell (le `PATH` de
  l'utilisateur vient d'être mis à jour).
- **Le démon ne répond pas.** Lance `omniscient group serve` dans un terminal pour voir
  l'erreur ; le port par défaut est 7341.
- **Le widget ne se couple pas.** Voir [omnigroup.md](omnigroup.md) (section couplage).

## Pour les mainteneurs

Une étiquette `widget-vX.Y.Z` fait construire l'installeur du widget **et** la roue du moteur ;
tous deux, avec `SHA256SUMS` et l'attestation de provenance, sont attachés à une release en
brouillon que le propriétaire publie. `install.ps1` lit la dernière release *publiée* : tant
qu'elle n'est pas publiée, la commande ne la voit pas. Garde le numéro de version de
`pyproject.toml` et celui de `widget/src-tauri/tauri.conf.json` alignés avant d'étiqueter.
La CI (`install-smoke`) exécute le script sur un Windows vierge, avec PowerShell 5.1 et 7.
