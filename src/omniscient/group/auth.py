"""omniscient accounts: sign in with Google or GitHub, or with an e-mail and a password,
through Supabase Auth (the "cheapest" hosted login that supports all three).

Everything happens in the daemon, which already speaks HTTPS; the widget never touches a
token. Browser sign-in is OAuth with PKCE (RFC 7636): the daemon makes a one-time
verifier, sends the browser to Supabase with its SHA-256 challenge, and the browser comes
back to `http://127.0.0.1:<port>/auth/callback?code=…`. The code only works with *our*
verifier, so a code planted by someone else (login CSRF) is useless; a flow lives 10
minutes and a few tries.

What is kept: `auth_config.json` (the project URL and its public "anon" key, which is
meant to be public) and `auth_session.json` (the refresh token and who is signed in), both
0600 in the 0700 state folder. No route ever returns a token. A hosted account carries
identity only: provider keys and conversations stay on the person's machine.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from omniscient.group import auth_pages
from omniscient.group.credentials import secure_dir, write_atomic
from omniscient.group.providers import ProviderError, Resolver, check_destination

log = logging.getLogger(__name__)

PROVIDERS = ("google", "github")
ENV_URL, ENV_KEY = "OMNISCIENT_AUTH_URL", "OMNISCIENT_AUTH_ANON_KEY"
ANON_KEY = re.compile(r"^[A-Za-z0-9._-]{16,2048}$")
AUTH_CODE = re.compile(r"^[A-Za-z0-9_-]{8,200}$")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)*\.[^@\s.]{2,63}")
EMAIL_MAX = 254
PASSWORD_MIN, PASSWORD_MAX = 8, 128
PENDING_TTL_S = 600
MAX_CALLBACK_ATTEMPTS = 3
MAX_PASSWORD_ATTEMPTS = 8
ATTEMPT_WINDOW_S = 600
REFRESH_SKEW_S = 60
MAX_REPLY_BYTES = 256 * 1024
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
NOT_CONFIGURED = "Comptes non configurés : voir docs/accounts.md."

# 422, never 401/403: the widget's client reads those two as "your widget token was refused".
REFUSED = 422
_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_credentials": (REFUSED, "E-mail ou mot de passe incorrect."),
    "email_not_confirmed": (
        401,
        "Confirmez d'abord votre e-mail (lien reçu par courrier).",
    ),
    "user_already_exists": (
        409,
        "Un compte existe déjà avec cet e-mail : connectez-vous.",
    ),
    "email_exists": (409, "Un compte existe déjà avec cet e-mail : connectez-vous."),
    "weak_password": (
        400,
        "Mot de passe trop faible : choisissez-en un plus long ou plus varié.",
    ),
    "signup_disabled": (REFUSED, "Les inscriptions sont fermées."),
    "over_request_rate_limit": (
        429,
        "Trop de tentatives : réessayez dans quelques minutes.",
    ),
    "over_email_send_rate_limit": (
        429,
        "Trop d'e-mails envoyés : réessayez dans quelques minutes.",
    ),
}


class AuthError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class AuthConfig:
    url: str
    anon_key: str

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""


@dataclass
class Pending:
    """A sign-in waiting for its browser round trip (in memory only)."""

    verifier: str
    started: float
    attempts: int = 0


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


SECRET_PREFIX = "sb_secret_"
SECRET_KEY_MESSAGE = (
    "Clé secrète refusée : donnez la clé publique (sb_publishable_… ou « anon »), "
    "jamais une clé secrète ni service_role."
)


def _is_secret_key(key: str) -> bool:
    """A Supabase secret key: `sb_secret_…`, or a legacy JWT whose role is service_role."""
    if key.startswith(SECRET_PREFIX):
        return True
    parts = key.split(".")
    if len(parts) != 3:
        return False
    try:
        claims = json.loads(
            base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        )
    except (ValueError, UnicodeDecodeError):
        return False  # not a JWT we can read: the format check below still applies
    return isinstance(claims, dict) and claims.get("role") == "service_role"


def validate_config(
    url: Any, anon_key: Any, resolver: Resolver = socket.getaddrinfo
) -> AuthConfig:
    if not isinstance(url, str) or not isinstance(anon_key, str):
        raise AuthError(400, "Adresse ou clé invalide.")
    try:
        clean = check_destination(url, resolver)
    except ProviderError as exc:
        raise AuthError(400, exc.message) from exc
    if urlsplit(clean).path not in ("", "/"):
        raise AuthError(400, "L'adresse du service ne doit pas contenir de chemin.")
    if not ANON_KEY.match(anon_key):
        raise AuthError(400, "Clé publique invalide.")
    if _is_secret_key(anon_key):
        raise AuthError(400, SECRET_KEY_MESSAGE)
    return AuthConfig(clean.rstrip("/"), anon_key)


def _map_error(status: int, payload: Any) -> AuthError:
    code = ""
    if isinstance(payload, dict):
        raw = payload.get("error_code") or payload.get("error") or ""
        code = raw if isinstance(raw, str) else ""
    if code in _ERRORS:
        return AuthError(*_ERRORS[code])
    if status == 429:
        return AuthError(429, "Trop de tentatives : réessayez dans quelques minutes.")
    if status >= 500:
        return AuthError(502, "Le service de comptes est indisponible.")
    return AuthError(REFUSED, "Connexion refusée ou expirée : recommencez.")


class AuthService:
    """Config, the browser flow, password sign-in and the saved session (thread-safe)."""

    def __init__(
        self,
        state_dir: Path,
        publish: Callable[[str, dict[str, Any]], None],
        *,
        client: httpx.Client | None = None,
        resolver: Resolver = socket.getaddrinfo,
        clock: Callable[[], float] = time.time,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._dir = state_dir
        self._publish = publish
        self._client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        self._resolver = resolver
        self._clock = clock
        self._env = os.environ if env is None else env
        self._lock = threading.RLock()
        self._port = 7341
        self._pending: Pending | None = None
        self._notice = ""
        self._attempts: deque[float] = deque()
        self._access: tuple[str, float] | None = (
            None  # access token, expiry (memory only)
        )

    def set_port(self, port: int) -> None:
        self._port = port

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._port}/auth/callback"

    # -- config --

    def config(self) -> AuthConfig | None:
        url, key = self._env.get(ENV_URL), self._env.get(ENV_KEY)
        if not (url and key):
            saved = self._read("auth_config.json")
            url, key = saved.get("url"), saved.get("anon_key")
        if not (url and key):
            return None
        try:
            return validate_config(url, key, self._resolver)
        except AuthError as exc:
            log.warning("omniscient accounts: configuration ignored (%s)", exc.message)
            return None

    def configure(self, url: Any, anon_key: Any) -> AuthConfig:
        cfg = validate_config(url, anon_key, self._resolver)
        self._write("auth_config.json", {"url": cfg.url, "anon_key": cfg.anon_key})
        return cfg

    def unconfigure(self) -> None:
        (self._dir / "auth_config.json").unlink(missing_ok=True)

    def _need_config(self) -> AuthConfig:
        cfg = self.config()
        if cfg is None:
            raise AuthError(409, NOT_CONFIGURED)
        return cfg

    # -- files --

    def _read(self, name: str) -> dict[str, Any]:
        try:
            data = json.loads((self._dir / name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("omniscient accounts: %s ignored (%s)", name, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, name: str, data: dict[str, Any]) -> None:
        secure_dir(self._dir)
        write_atomic(self._dir / name, json.dumps(data, ensure_ascii=False))

    # -- HTTP --

    def _call(
        self, cfg: AuthConfig, method: str, path: str, *,
        params: dict[str, str] | None = None, body: dict[str, Any] | None = None, bearer: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        url = f"{cfg.url}{path}"
        try:
            check_destination(url, self._resolver)  # again, right before the call
        except ProviderError as exc:
            raise AuthError(400, exc.message) from exc
        # The project key goes in `apikey` only: `Authorization` carries a user's token,
        # and a new-format key (sb_publishable_…) is not a JWT.
        headers = {"apikey": cfg.anon_key}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        try:
            with self._client.stream(
                method, url, params=params, json=body, headers=headers
            ) as resp:
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_REPLY_BYTES:
                        raise AuthError(
                            502, "Réponse du service de comptes trop volumineuse."
                        )
                    chunks.append(chunk)
                status, raw = resp.status_code, b"".join(chunks)
        except httpx.HTTPError as exc:
            log.warning(
                "omniscient accounts: %s %s: %s", method, path, type(exc).__name__
            )
            raise AuthError(502, "Le service de comptes est injoignable.") from exc
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {}
        if status >= 400:
            raise _map_error(status, payload)
        return payload if isinstance(payload, dict) else {}

    # -- session --

    @staticmethod
    def _user_view(raw: Any, fallback_provider: str = "email") -> dict[str, str]:
        raw = raw if isinstance(raw, dict) else {}
        meta = (
            raw.get("user_metadata")
            if isinstance(raw.get("user_metadata"), dict)
            else {}
        )
        app_meta = (
            raw.get("app_metadata") if isinstance(raw.get("app_metadata"), dict) else {}
        )
        name = next(
            (
                meta[k]
                for k in ("full_name", "name", "user_name")
                if isinstance(meta.get(k), str)
            ),
            "",
        )
        provider = app_meta.get("provider")
        return {
            "email": str(raw.get("email") or "")[:EMAIL_MAX],
            "name": name[:80],
            "provider": provider
            if provider in (*PROVIDERS, "email")
            else fallback_provider,
        }

    def _store_session(self, data: dict[str, Any]) -> None:
        access, refresh = data.get("access_token"), data.get("refresh_token")
        if not (isinstance(access, str) and isinstance(refresh, str)):
            raise AuthError(502, "Réponse du service de comptes incomplète.")
        expires_in = data.get("expires_in")
        ttl = float(expires_in) if isinstance(expires_in, (int, float)) else 3600.0
        with self._lock:
            old = (
                self._read("auth_session.json").get("user")
                if "user" not in data
                else None
            )
            user = self._user_view(data["user"]) if "user" in data else (old or {})
            self._write(
                "auth_session.json",
                {"refresh_token": refresh, "user": user, "saved_at": self._clock()},
            )
            self._access = (access, self._clock() + ttl)
            self._notice = ""

    def _forget(self) -> None:
        with self._lock:
            (self._dir / "auth_session.json").unlink(missing_ok=True)
            self._access = None

    def access_token(self) -> str | None:
        """A valid access token (refreshed and rotated when needed), or None when signed out."""
        with self._lock:
            if self._access and self._access[1] - REFRESH_SKEW_S > self._clock():
                return self._access[0]
            refresh = self._read("auth_session.json").get("refresh_token")
            cfg = self.config()
            if not isinstance(refresh, str) or cfg is None:
                return None
            try:
                data = self._call(
                    cfg,
                    "POST",
                    "/auth/v1/token",
                    params={"grant_type": "refresh_token"},
                    body={"refresh_token": refresh},
                )
                self._store_session(data)
            except AuthError as exc:
                log.warning("omniscient accounts: refresh failed (%s)", exc.message)
                # the session is dead, not just unreachable
                if exc.status in (400, REFUSED):
                    self._forget()
                    self._publish("auth", self.status())
                return None
            return self._access[0] if self._access else None

    # -- status --

    def status(self) -> dict[str, Any]:
        with self._lock:
            cfg = self.config()
            user = self._read("auth_session.json").get("user")
            signed_in = isinstance(user, dict) and bool(user.get("email"))
            view = (
                {k: str(user.get(k, "")) for k in ("email", "name", "provider")}
                if signed_in and isinstance(user, dict)
                else None
            )
            return {
                "configured": cfg is not None,
                "host": cfg.host if cfg else "",
                "signed_in": signed_in,
                "user": view,
                "pending": self._live_pending() is not None,
                "providers": list(PROVIDERS) if cfg else [],
                "message": self._notice,
            }

    def _changed(self) -> dict[str, Any]:
        view = self.status()
        try:
            self._publish("auth", view)
        except Exception:
            log.exception("omniscient accounts: event not published")
        return view

    # -- browser flow --

    def _live_pending(self) -> Pending | None:
        pending = self._pending
        if pending is not None and self._clock() - pending.started > PENDING_TTL_S:
            self._pending = None
            return None
        return pending

    def _new_flow(self) -> tuple[Pending, str]:
        verifier = secrets.token_urlsafe(48)  # 64 characters, within RFC 7636's 43-128
        pending = Pending(verifier, self._clock())
        self._pending = pending
        return pending, _challenge(verifier)

    def start(self, provider: Any) -> dict[str, Any]:
        if provider not in PROVIDERS:
            raise AuthError(400, "Fournisseur de connexion inconnu.")
        cfg = self._need_config()
        with self._lock:
            _, challenge = self._new_flow()
            self._notice = ""
        query = urlencode(
            {"provider": provider, "redirect_to": self.redirect_uri,
             "code_challenge": challenge, "code_challenge_method": "s256"}
        )  # fmt: skip
        self._changed()
        return {
            "url": f"{cfg.url}/auth/v1/authorize?{query}",
            "expires_in": PENDING_TTL_S,
        }

    def callback(self, query: Mapping[str, Any]) -> tuple[int, str]:
        """The browser came back (`/auth/callback`): finish the flow, return (status, page)."""
        if "error" in query:  # the person refused, or the provider did
            with self._lock:
                self._pending = None
            self._changed()
            return 400, auth_pages.cancelled()
        with self._lock:
            pending = self._live_pending()
            if pending is None:
                return 400, auth_pages.expired()
            pending.attempts += 1
            code = query.get("code")
            if not isinstance(code, str) or not AUTH_CODE.match(code):
                self._drop_if_spent(pending)
                return 400, auth_pages.failed()
        try:
            data = self._call(self._need_config(), "POST", "/auth/v1/token", params={"grant_type": "pkce"},
                              body={"auth_code": code, "code_verifier": pending.verifier})  # fmt: skip
            self._store_session(data)
        except AuthError as exc:
            log.info("omniscient accounts: browser sign-in refused (%s)", exc.message)
            with self._lock:
                self._drop_if_spent(pending)
            self._changed()
            return 400, auth_pages.failed()
        with self._lock:
            self._pending = None
        self._changed()
        return 200, auth_pages.success()

    def _drop_if_spent(self, pending: Pending) -> None:
        if pending.attempts >= MAX_CALLBACK_ATTEMPTS and self._pending is pending:
            self._pending = None

    # -- e-mail + password --

    def _allow_attempt(self) -> None:
        with self._lock:
            now = self._clock()
            while self._attempts and now - self._attempts[0] >= ATTEMPT_WINDOW_S:
                self._attempts.popleft()
            if len(self._attempts) >= MAX_PASSWORD_ATTEMPTS:
                raise AuthError(
                    429, "Trop de tentatives : réessayez dans quelques minutes."
                )
            self._attempts.append(now)

    def password(self, mode: Any, email: Any, password: Any) -> dict[str, Any]:
        if mode not in ("signin", "signup"):
            raise AuthError(400, "Action inconnue.")
        if (
            not isinstance(email, str)
            or len(email) > EMAIL_MAX
            or not EMAIL.fullmatch(email)
        ):
            raise AuthError(400, "Adresse e-mail invalide.")
        if (
            not isinstance(password, str)
            or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX
        ):
            raise AuthError(
                400,
                f"Le mot de passe doit faire {PASSWORD_MIN} à {PASSWORD_MAX} caractères.",
            )
        cfg = self._need_config()
        self._allow_attempt()
        if mode == "signin":
            self._store_session(
                self._call(
                    cfg,
                    "POST",
                    "/auth/v1/token",
                    params={"grant_type": "password"},
                    body={"email": email, "password": password},
                )
            )
            return self._changed()
        with self._lock:
            _, challenge = self._new_flow()
        data = self._call(
            cfg, "POST", "/auth/v1/signup", params={"redirect_to": self.redirect_uri},
            body={"email": email, "password": password, "code_challenge": challenge, "code_challenge_method": "s256"},
        )  # fmt: skip
        with self._lock:
            if (
                "access_token" in data
            ):  # this project does not ask for e-mail confirmation
                self._pending = None
                self._store_session(data)
            else:
                self._notice = f"Un e-mail de confirmation vient d'être envoyé à {email}. Cliquez sur le lien, puis revenez ici."
        return self._changed()

    # -- sign out --

    def signout(self) -> dict[str, Any]:
        cfg = self.config()
        token = self.access_token() if cfg else None
        if cfg and token:
            try:
                self._call(cfg, "POST", "/auth/v1/logout", bearer=token)
            except (
                AuthError
            ) as exc:  # signing out locally still works when the service is down
                log.warning(
                    "omniscient accounts: remote sign-out failed (%s)", exc.message
                )
        with self._lock:
            self._forget()
            self._pending = None
            self._notice = ""
        return self._changed()
