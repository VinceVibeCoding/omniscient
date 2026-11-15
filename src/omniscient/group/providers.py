"""LLM providers a widget chat can use besides Claude Code (the built-in default).

A person who only has a Gemini or an OpenAI key can still chat: each provider is a small
record (kind, label, model, address) in `<home>/.omniscient/providers.json`, and its API
key lives apart in `provider_keys.json`. Both files are 0600 in the 0700 state folder.
The key is write-only: no route ever returns it, only « has a key » and its last 4
characters. Claude Code stays the default and needs no key here (it uses the person's
own login).

A provider address is a place the daemon sends the key to, so it is checked: https to a
public host, or http(s) to the machine itself (a local model such as Ollama). Private
networks, link-local and metadata addresses, and names that resolve to them are refused,
at save time and again right before each call.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from omniscient.group.credentials import secure_dir, write_atomic

log = logging.getLogger(__name__)

CLAUDE_CODE = "claude-code"
KINDS = ("openai", "gemini", "anthropic", "openai-compatible")
FIXED_BASES = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
    "anthropic": "https://api.anthropic.com",
}
KIND_LABELS = {
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "anthropic": "Anthropic (API)",
    "openai-compatible": "Compatible OpenAI (Ollama, LM Studio, OpenRouter…)",
}
PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")
API_KEY = re.compile(r"^[\x21-\x7e]{8,512}$")
LABEL_MAX = 60
MAX_PROVIDERS = 12
MAX_TESTS_PER_HOUR = 20
HOUR_S = 3600

Resolver = Callable[..., list[Any]]


class ProviderError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Provider:
    id: str
    kind: str
    label: str
    base_url: str
    model: str

    def view(self, has_key: bool, key: str | None) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "builtin": False,
            "has_key": has_key,
            "key_hint": key[-4:] if key else "",
        }


# ---- destination guard ---------------------------------------------------------------


def _addresses(
    host: str, port: int, resolver: Resolver
) -> list[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass
    try:
        infos = resolver(host, port, 0, socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderError(400, f"Adresse introuvable : {host[:80]}") from exc
    found = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not found:
        raise ProviderError(400, f"Adresse introuvable : {host[:80]}")
    return found


def check_destination(url: str, resolver: Resolver = socket.getaddrinfo) -> str:
    """The normalised URL when it is safe to send a key to, else a 400 ProviderError."""
    try:
        parts = urlsplit(url.strip())
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise ProviderError(400, "Adresse invalide.") from exc
    if parts.scheme not in ("http", "https") or not host:
        raise ProviderError(
            400, "L'adresse doit commencer par https:// (ou http:// en local)."
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ProviderError(
            400, "L'adresse ne doit contenir ni identifiants, ni paramètres, ni ancre."
        )
    normalised = url.strip().rstrip("/")
    if (
        host.lower() == "localhost"
    ):  # the machine itself, like browsers: no DNS involved
        return normalised
    addrs = _addresses(host, port or (443 if parts.scheme == "https" else 80), resolver)
    if len(addrs) == 1 and host.strip("[]") == str(addrs[0]) and addrs[0].is_loopback:
        return normalised  # a loopback address literal (127.0.0.1, ::1)
    if parts.scheme != "https":
        raise ProviderError(
            400, "Hors de cette machine, l'adresse doit être en https://."
        )
    if not all(a.is_global for a in addrs):
        raise ProviderError(400, "Cette adresse pointe vers un réseau privé : refusée.")
    return normalised


# ---- field validation ----------------------------------------------------------------


def _check_id(pid: Any) -> str:
    if not isinstance(pid, str) or not PROVIDER_ID.match(pid) or pid == CLAUDE_CODE:
        raise ProviderError(400, "Identifiant de fournisseur invalide.")
    return pid


def _check_key(raw: Any) -> str:
    if not isinstance(raw, str) or not API_KEY.match(raw):
        raise ProviderError(
            400, "Clé invalide : 8 à 512 caractères visibles, sans espace."
        )
    return raw


def _clean(body: dict[str, Any], old: Provider | None, resolver: Resolver) -> Provider:
    kind = body.get("kind", old.kind if old else None)
    if kind not in KINDS:
        raise ProviderError(400, "Type de fournisseur inconnu.")
    label = body.get("label", old.label if old else KIND_LABELS[kind])
    if (
        not isinstance(label, str)
        or not label.strip()
        or len(label.strip()) > LABEL_MAX
    ):
        raise ProviderError(400, f"Nom invalide ({LABEL_MAX} caractères au plus).")
    model = body.get("model", old.model if old else "")
    # "" = not chosen yet: add the key, test it to list the models, then pick one.
    if not isinstance(model, str) or (model != "" and not MODEL.match(model)):
        raise ProviderError(
            400, "Modèle invalide : lettres, chiffres et . _ : / @ + - seulement."
        )
    if kind in FIXED_BASES:
        base = FIXED_BASES[kind]
    else:
        raw = body.get("base_url", old.base_url if old else "")
        base = check_destination(raw, resolver) if isinstance(raw, str) and raw else ""
        if not base:
            raise ProviderError(400, "Indiquez l'adresse du serveur compatible OpenAI.")
    return Provider(old.id if old else "", kind, label.strip(), base, model)


# ---- the store -----------------------------------------------------------------------


class ProviderStore:
    """Providers on disk (0600), keys in a separate 0600 file; safe across threads."""

    def __init__(
        self,
        state_dir: Path,
        resolver: Resolver = socket.getaddrinfo,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._dir = state_dir
        self._resolver = resolver
        self._clock = clock
        self._lock = threading.Lock()
        self._tests: deque[float] = deque()

    @property
    def resolver(self) -> Resolver:
        return self._resolver

    def _read(self, name: str) -> dict[str, Any]:
        path = self._dir / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("omnigroup providers: %s ignored (%s)", name, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, name: str, data: dict[str, Any]) -> None:
        secure_dir(self._dir)
        write_atomic(self._dir / name, json.dumps(data, ensure_ascii=False, indent=2))

    def _load(self) -> tuple[dict[str, Provider], str, dict[str, str]]:
        raw = self._read("providers.json")
        providers: dict[str, Provider] = {}
        for pid, item in (raw.get("providers") or {}).items():
            try:
                providers[pid] = Provider(
                    pid, item["kind"], item["label"], item["base_url"], item["model"]
                )
            except (KeyError, TypeError) as exc:
                log.warning("omnigroup providers: %s ignored (%s)", pid, exc)
        keys = {
            k: v
            for k, v in self._read("provider_keys.json").items()
            if isinstance(v, str)
        }
        default = raw.get("default")
        return providers, default if default in providers else CLAUDE_CODE, keys

    def _save(
        self, providers: dict[str, Provider], default: str, keys: dict[str, str]
    ) -> None:
        listing = {
            pid: {k: v for k, v in vars(p).items() if k != "id"}
            for pid, p in providers.items()
        }
        self._write("providers.json", {"providers": listing, "default": default})
        self._write(
            "provider_keys.json", {pid: keys[pid] for pid in providers if pid in keys}
        )

    # -- public --

    def listing(self) -> dict[str, Any]:
        with self._lock:
            providers, default, keys = self._load()
        builtin = {
            "id": CLAUDE_CODE, "kind": CLAUDE_CODE, "label": "Claude Code", "base_url": "",
            "model": "", "builtin": True, "has_key": False, "key_hint": "",
        }  # fmt: skip
        items = [builtin] + [
            p.view(p.id in keys, keys.get(p.id)) for p in providers.values()
        ]
        return {"providers": items, "default": default}

    def get(self, pid: str) -> tuple[Provider, str | None] | None:
        with self._lock:
            providers, _, keys = self._load()
        provider = providers.get(pid)
        return (provider, keys.get(pid)) if provider else None

    def upsert(self, pid: Any, body: dict[str, Any]) -> dict[str, Any]:
        pid = _check_id(pid)
        with self._lock:
            providers, default, keys = self._load()
            old = providers.get(pid)
            if old is None and len(providers) >= MAX_PROVIDERS:
                raise ProviderError(400, f"{MAX_PROVIDERS} fournisseurs au plus.")
            provider = replace(_clean(body, old, self._resolver), id=pid)
            if "api_key" in body:
                keys = {**keys, pid: _check_key(body["api_key"])}
            if provider.kind != "openai-compatible" and pid not in keys:
                raise ProviderError(400, "Ce fournisseur demande une clé API.")
            providers = {**providers, pid: provider}
            if body.get("default") is True:
                default = pid
            self._save(providers, default, keys)
            return provider.view(pid in keys, keys.get(pid))

    def remove(self, pid: Any) -> None:
        if pid == CLAUDE_CODE:
            raise ProviderError(400, "Claude Code est intégré : il ne se retire pas.")
        pid = _check_id(pid)
        with self._lock:
            providers, default, keys = self._load()
            if pid not in providers:
                raise ProviderError(404, "Fournisseur inconnu.")
            providers = {k: v for k, v in providers.items() if k != pid}
            keys = {k: v for k, v in keys.items() if k != pid}
            self._save(providers, CLAUDE_CODE if default == pid else default, keys)

    def allow_test(self) -> None:
        """Counts one outbound test call; 429 past MAX_TESTS_PER_HOUR."""
        with self._lock:
            now = self._clock()
            while self._tests and now - self._tests[0] >= HOUR_S:
                self._tests.popleft()
            if len(self._tests) >= MAX_TESTS_PER_HOUR:
                raise ProviderError(
                    429, "Trop d'essais de connexion : réessayez plus tard."
                )
            self._tests.append(now)
