#!/bin/sh
# Omniscient - installation en une commande (Linux, macOS, WSL ; sans root ni sudo).
#
#   curl -fsSL https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.sh | sh
#
# Ce que le script fait (détails : docs/install.md) :
#   1. trouve ou installe uv (installeur officiel astral.sh) ;
#   2. installe le moteur depuis la roue (.whl) de la dernière version GitHub, SHA-256 vérifié, sans git ;
#   3. lance le démon (service systemd utilisateur si possible, sinon en arrière-plan) ;
#   4. écrit les hooks Claude Code (sauvegarde d'abord) ; sous WSL, installe aussi le widget Windows ;
#   5. affiche l'état et la suite.
# Relancer le script met tout à jour. Rien n'est écrit hors de ton dossier personnel.
#
# Options (pour les tests ; la commande ci-dessus n'en a pas besoin), via `sh -s -- OPTIONS` :
#   --wheel CHEMIN   roue locale à installer au lieu de la dernière version publiée
#   --skip-widget    ne pas installer le widget (WSL)
#   --no-daemon      ne pas lancer le démon
#   --port N         port du démon (défaut : 7341)
#   --help           cette aide
# Variables équivalentes : OMNIGROUP_INSTALL_WHEEL, _SKIPWIDGET, _NODAEMON, _PORT.
set -eu

REPO='VinceVibeCoding/omniscient'
BASE="https://github.com/$REPO/releases/latest/download"
TOTAL=5
DEFAULT_PORT=7341

WHEEL=${OMNIGROUP_INSTALL_WHEEL:-}
SKIP_WIDGET=${OMNIGROUP_INSTALL_SKIPWIDGET:-}
NO_DAEMON=${OMNIGROUP_INSTALL_NODAEMON:-}
PORT=${OMNIGROUP_INSTALL_PORT:-$DEFAULT_PORT}
WORK=''
OMNI=''

if [ -t 1 ]; then
    C_STEP=$(printf '\033[36m'); C_OK=$(printf '\033[32m'); C_WARN=$(printf '\033[33m')
    C_ERR=$(printf '\033[31m'); C_OFF=$(printf '\033[0m')
else
    C_STEP=''; C_OK=''; C_WARN=''; C_ERR=''; C_OFF=''
fi

step() { printf '\n%s[%s/%s] %s%s\n' "$C_STEP" "$1" "$TOTAL" "$2" "$C_OFF"; }
info() { printf '      %s\n' "$1"; }
ok() { printf '%s  OK  %s%s\n' "$C_OK" "$1" "$C_OFF"; }
warn() { printf '%s  !!  %s%s\n' "$C_WARN" "$1" "$C_OFF"; }

cleanup() {
    if [ -n "$WORK" ] && [ -d "$WORK" ]; then rm -rf "$WORK"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

die() {
    printf '\n%sERREUR : %s%s\n' "$C_ERR" "$1" "$C_OFF" >&2
    printf "%sRien de grave : tu peux relancer la commande après avoir corrigé. Aide : https://github.com/%s/blob/main/docs/install.md%s\n" "$C_WARN" "$REPO" "$C_OFF" >&2
    if [ -n "$OMNI" ] && [ -x "$OMNI" ]; then
        printf '%sPour demander de l'"'"'aide : lance "omniscient group doctor" et colle le résultat (rien de secret n'"'"'y figure).%s\n' "$C_WARN" "$C_OFF" >&2
    else
        printf '%sUne fois le moteur installé, "omniscient group doctor" donne un diagnostic à coller dans un rapport.%s\n' "$C_WARN" "$C_OFF" >&2
    fi
    exit 1
}

usage() {
    cat <<'EOT'
Omniscient - installation (Linux, macOS, WSL).
Usage : curl -fsSL https://raw.githubusercontent.com/VinceVibeCoding/omniscient/main/install.sh | sh -s -- [OPTIONS]
  --wheel CHEMIN   roue locale à installer au lieu de la dernière version publiée
  --skip-widget    ne pas installer le widget (WSL)
  --no-daemon      ne pas lancer le démon
  --port N         port du démon (défaut : 7341)
  --help           cette aide
Variables : OMNIGROUP_INSTALL_WHEEL, _SKIPWIDGET, _NODAEMON, _PORT.
EOT
}

# ---- options ----------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --wheel) [ $# -ge 2 ] || die "--wheel attend un chemin."; WHEEL=$2; shift 2 ;;
        --port) [ $# -ge 2 ] || die "--port attend un numéro."; PORT=$2; shift 2 ;;
        --skip-widget) SKIP_WIDGET=1; shift ;;
        --no-daemon) NO_DAEMON=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "option inconnue : $1 (voir --help)." ;;
    esac
done
case "$PORT" in
    ''|*[!0-9]*) die "port invalide : $PORT" ;;
esac
{ [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ]; } || die "port hors de 1024-65535 : $PORT"
[ -n "${HOME:-}" ] && [ -d "$HOME" ] || die "la variable HOME n'est pas définie ou son dossier n'existe pas."

# ---- helpers ----------------------------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

# fetch URL DEST : https seulement, curl ou wget.
fetch() {
    case "$1" in https://*) ;; *) die "URL non HTTPS refusée : $1" ;; esac
    if have curl; then
        curl --proto '=https' --tlsv1.2 -fsSL --retry 2 -o "$2" "$1"
    elif have wget; then
        wget -q --https-only --secure-protocol=TLSv1_2 -O "$2" "$1"
    else
        die "ni curl ni wget n'est installé : installe l'un des deux, puis relance."
    fi
}

sha256_of() {
    if have sha256sum; then sha256sum "$1" | awk '{print $1}'
    elif have shasum; then shasum -a 256 "$1" | awk '{print $1}'
    else die "ni sha256sum ni shasum n'est installé : impossible de vérifier la roue."
    fi
}

is_wsl() {
    if [ -n "${WSL_DISTRO_NAME:-}" ]; then return 0; fi
    [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null
}

has_systemd_user() {
    have systemctl && systemctl --user show-environment >/dev/null 2>&1
}

daemon_up() { "$OMNI" group status --port "$PORT" >/dev/null 2>&1; }

wait_for_daemon() {
    i=0
    while [ "$i" -lt 30 ]; do
        if daemon_up; then return 0; fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

add_path() {
    case ":$PATH:" in *":$1:"*) ;; *) PATH="$1:$PATH"; export PATH ;; esac
}

# ---- 1. uv ------------------------------------------------------------------------------
install_uv() {
    step 1 'uv (gestionnaire Python)'
    add_path "$HOME/.local/bin"
    if have uv && uv --version >/dev/null 2>&1; then
        ok 'uv est déjà installé.'
        return
    fi
    info "Installation de uv avec l'installeur officiel (astral.sh)..."
    have curl || die "curl est requis pour installer uv : installe-le, ou installe uv à la main (https://docs.astral.sh/uv/) puis relance."
    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh >/dev/null \
        || die "uv n'a pas pu être installé. Installe-le à la main (https://docs.astral.sh/uv/), puis relance ce script."
    add_path "$HOME/.local/bin"
    have uv || die "uv est installé mais introuvable dans le PATH : ouvre un nouveau terminal et relance."
    ok 'uv installé.'
}

# ---- 2. moteur --------------------------------------------------------------------------
latest_wheel() {
    sums="$WORK/SHA256SUMS"
    info 'Recherche de la dernière version publiée...'
    fetch "$BASE/SHA256SUMS" "$sums" \
        || die "impossible de lire la dernière version sur GitHub. Vérifie ta connexion Internet (ou ton proxy) et relance."
    name=$(awk '$2 ~ /^\*?omniscient-[0-9][0-9A-Za-z.+!_-]*-py3-none-any\.whl$/ { sub(/^\*/, "", $2); print $2; exit }' "$sums")
    [ -n "$name" ] || die "la dernière version ne contient pas encore le moteur (roue .whl + SHA256SUMS). Réessaie plus tard ou suis l'installation manuelle du README."
    expected=$(awk -v n="$name" '{ f = $2; sub(/^\*/, "", f) } f == n && $1 ~ /^[0-9a-fA-F]{64}$/ { print tolower($1); exit }' "$sums")
    [ -n "$expected" ] || die "$name est absent de SHA256SUMS : installation refusée."
    info "Téléchargement de $name..."
    fetch "$BASE/$name" "$WORK/$name" || die "téléchargement de $name impossible."
    actual=$(sha256_of "$WORK/$name")
    [ "$actual" = "$expected" ] || die "SHA-256 différent pour $name (attendu $expected, obtenu $actual) : fichier rejeté, rien n'a été installé."
    ok "SHA-256 vérifié ($actual)"
    WHEEL_PATH="$WORK/$name"
}

install_engine() {
    step 2 'Moteur Omniscient (sans git)'
    if [ -n "$WHEEL" ]; then
        case "$WHEEL" in *.whl) ;; *) die "--wheel : ce n'est pas une roue (.whl) : $WHEEL" ;; esac
        [ -f "$WHEEL" ] || die "--wheel : roue introuvable : $WHEEL"
        WHEEL_PATH="$(cd "$(dirname "$WHEEL")" && pwd)/$(basename "$WHEEL")"
        warn "Roue locale (pas de vérification SHA-256) : $WHEEL_PATH"
    else
        latest_wheel
    fi
    info 'Installation (uv télécharge Python 3.12+ si besoin)...'
    uv tool install --force "$WHEEL_PATH" || die "uv n'a pas pu installer le moteur (voir ci-dessus)."
    uv tool update-shell >/dev/null 2>&1 || true
    bin=$(uv tool dir --bin) || die "uv ne dit pas où sont ses outils."
    add_path "$bin"
    OMNI="$bin/omniscient"
    [ -x "$OMNI" ] || die "omniscient est introuvable dans $bin après l'installation."
    "$OMNI" --version >/dev/null 2>&1 || die "omniscient --version a échoué."
    ok "Moteur installé ($("$OMNI" --version 2>/dev/null))."
}

# ---- 3. démon ---------------------------------------------------------------------------
start_with_systemd() {
    "$OMNI" schedule install --write >/dev/null 2>&1 || return 1
    systemctl --user daemon-reload || return 1
    systemctl --user enable omnigroup.service >/dev/null 2>&1 || return 1
    systemctl --user restart omnigroup.service || return 1
}

start_detached() {
    state="$HOME/.omniscient"
    mkdir -p "$state"
    log="$state/daemon.log"
    nohup "$OMNI" group serve --port "$PORT" >"$log" 2>&1 </dev/null &
    info "Démon lancé en arrière-plan (journal : $log)."
    info "Pour le relancer plus tard : nohup omniscient group serve >/dev/null 2>&1 &"
}

install_daemon() {
    step 3 'Démon'
    if [ -n "$NO_DAEMON" ]; then
        info '--no-daemon : démon non lancé (lance "omniscient group serve" quand tu en as besoin).'
        return
    fi
    if daemon_up; then
        ok "Un démon répond déjà sur http://127.0.0.1:$PORT (relance-le pour qu'il prenne la mise à jour)."
        return
    fi
    "$OMNI" group serve --check-port --port "$PORT" \
        || die "le port $PORT est inutilisable pour le démon (voir ci-dessus) : relance avec un autre port, par exemple --port $((PORT + 10))."
    if [ "$PORT" -eq "$DEFAULT_PORT" ] && has_systemd_user && start_with_systemd; then
        ok "Service systemd utilisateur 'omnigroup' activé (démarre à chaque ouverture de session)."
    else
        if [ "$PORT" -ne "$DEFAULT_PORT" ]; then
            warn "Port $PORT : les hooks suivent la variable OMNIGROUP_URL=http://127.0.0.1:$PORT (ajoute-la à ton profil shell)."
        fi
        start_detached
    fi
    wait_for_daemon || die "le démon ne répond pas sur le port $PORT. Lance 'omniscient group serve' dans un terminal pour voir l'erreur."
    ok "Le démon répond sur http://127.0.0.1:$PORT."
}

# ---- 4. hooks + widget ------------------------------------------------------------------
windows_temp_dir() {
    have cmd.exe && have wslpath || return 1
    winpath=$( (cd /mnt/c 2>/dev/null && cmd.exe /c 'echo %TEMP%') 2>/dev/null | tr -d '\r' | tail -n 1)
    case "$winpath" in [A-Za-z]:\\*) ;; *) return 1 ;; esac
    wslpath -u "$winpath" 2>/dev/null
}

install_widget() {
    wtemp=$(windows_temp_dir) || { warn "Interopérabilité Windows indisponible : widget non installé. Installe-le depuis le menu de la release GitHub."; return 0; }
    wdir=$(mktemp -d "$wtemp/omniscient-widget-XXXXXX") || { warn "Dossier temporaire Windows inaccessible : widget non installé."; return 0; }
    WIDGET_DIR="$wdir"
    "$OMNI" group setup --write --port "$PORT" --widget-dir "$wdir" --update-widget || die "omniscient group setup a échoué (voir ci-dessus)."
    setup_exe=''
    for f in "$wdir"/Omnigroup_*-setup.exe; do
        if [ -f "$f" ]; then setup_exe=$f; break; fi
    done
    if [ -z "$setup_exe" ]; then
        warn "L'installeur du widget n'a pas été téléchargé (voir ci-dessus) : relance plus tard, ou 'omniscient group setup --write'."
        return 0
    fi
    win_exe=$(wslpath -w "$setup_exe")
    info "Installation silencieuse du widget (pour ton utilisateur Windows)..."
    powershell.exe -NoProfile -Command "\$p = Start-Process -FilePath '$win_exe' -ArgumentList '/S' -Wait -PassThru; exit \$p.ExitCode" </dev/null \
        || die "l'installeur du widget a échoué."
    if powershell.exe -NoProfile -Command "\$a = Join-Path \$env:LOCALAPPDATA 'Omnigroup\\omnigroup.exe'; if (-not (Test-Path \$a)) { \$a = Join-Path \$env:LOCALAPPDATA 'Programs\\Omnigroup\\omnigroup.exe' }; if (Test-Path \$a) { Start-Process \$a; exit 0 } else { exit 1 }" </dev/null; then
        ok "Widget installé et lancé (menu Démarrer > Omnigroup)."
    else
        warn "Widget installé, mais pas lancé : ouvre Omnigroup depuis le menu Démarrer."
    fi
    rm -rf "$wdir"
}

install_hooks() {
    step 4 'Hooks Claude Code'
    if is_wsl && [ -z "$SKIP_WIDGET" ]; then
        info 'WSL détecté : hooks, puis widget Windows.'
        install_widget
        # install_widget ne lance setup que si l'interop marche : sinon, hooks seuls.
        if [ -z "${WIDGET_DIR:-}" ]; then
            "$OMNI" group setup --write --port "$PORT" --skip-widget || die "omniscient group setup a échoué (voir ci-dessus)."
        fi
    else
        "$OMNI" group setup --write --port "$PORT" --skip-widget || die "omniscient group setup a échoué (voir ci-dessus)."
        if ! is_wsl; then
            warn "Le widget est pour Windows pour l'instant (Mac : V2) ; en attendant, utilise 'omniscient' dans le terminal."
        fi
    fi
}

# ---- 5. état ----------------------------------------------------------------------------
final_status() {
    step 5 'État'
    "$OMNI" group status --port "$PORT" || warn "Le démon ne répond pas : lance 'omniscient group doctor'."
    printf '\n%sEt maintenant%s\n' "$C_OK" "$C_OFF"
    if is_wsl && [ -z "$SKIP_WIDGET" ]; then
        echo "  1. Ouvre Omnigroup (menu Démarrer de Windows)."
        echo "  2. Va dans Réglages > Demander un code, puis tape le code à 6 chiffres."
    else
        echo "  Pas de widget ici : utilise le terminal."
        echo "    omniscient --help           toutes les commandes"
        echo "    omniscient init             créer ton dossier Omniscient (profil, thème, projets)"
        echo "    omniscient studio           le tableau des idées (idéal dans herdr)"
        echo "    omniscient group status     l'état du démon"
    fi
    echo
    echo "  Mise à jour : relance la même commande. Désinstallation : docs/install.md."
    echo "  Un souci ? 'omniscient group doctor' donne un diagnostic à coller dans un rapport."
}

main() {
    printf '\nOmniscient - installation\n'
    WORK=$(mktemp -d "${TMPDIR:-/tmp}/omniscient-install-XXXXXX") || die "impossible de créer un dossier temporaire."
    install_uv
    install_engine
    install_daemon
    install_hooks
    final_status
}

main
