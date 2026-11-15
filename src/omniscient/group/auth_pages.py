"""The few static pages the browser lands on after signing in. No input is ever reflected
into them: every text here is fixed, so a crafted link cannot inject anything."""

from __future__ import annotations

_STYLE = (
    "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d1c;"
    "color:#ebe6d6;font:16px system-ui,sans-serif}main{max-width:26rem;padding:2rem;"
    "text-align:center}h1{font-size:1.3rem;margin:0 0 .6rem}p{color:#8a8fb3;margin:.3rem 0}"
    ".ok{color:#5fd39a}.ko{color:#ff6b81}"
)


def _page(heading: str, text: str, ok: bool) -> str:
    tone = "ok" if ok else "ko"
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Omnigroup</title><style>{_STYLE}</style></head><body><main>"
        f'<h1 class="{tone}">{heading}</h1><p>{text}</p></main></body></html>'
    )


def success() -> str:
    return _page(
        "Connecté ✓",
        "Vous pouvez fermer cet onglet et retourner dans le widget Omnigroup.",
        True,
    )


def confirmed() -> str:
    return _page(
        "E-mail confirmé ✓",
        "Retournez dans le widget Omnigroup pour vous connecter.",
        True,
    )


def expired() -> str:
    return _page(
        "Lien expiré",
        "Ce lien de connexion a expiré ou ne vient pas du widget. Retournez-y et recommencez.",
        False,
    )


def cancelled() -> str:
    return _page(
        "Connexion annulée",
        "Aucune connexion n'a été faite. Vous pouvez fermer cet onglet.",
        False,
    )


def failed() -> str:
    return _page(
        "Connexion impossible",
        "La connexion a échoué. Retournez dans le widget et recommencez.",
        False,
    )
