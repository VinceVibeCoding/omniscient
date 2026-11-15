"""Accounts: sign-in with Google / GitHub (PKCE through the browser), e-mail + password,
sessions kept 0600, no token ever returned (a fake in-memory Supabase Auth, no network)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from omniscient.group import auth as au

URL = "https://abcdefgh.supabase.co"
ANON = "eyJhbGciOiJIUzI1NiJ9.anon-public-key.sig"
PORT = 7341
CALLBACK = f"http://127.0.0.1:{PORT}/auth/callback"


def public(host: str, port: int = 443, *a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def user(email: str = "ana@example.com", provider: str = "google") -> dict[str, Any]:
    return {
        "id": "u-1",
        "email": email,
        "app_metadata": {"provider": provider},
        "user_metadata": {"full_name": "Ana Test", "avatar_url": "https://x/a.png"},
    }


class FakeGoTrue:
    """Just enough of Supabase Auth: authorize, token (pkce/password/refresh), signup, logout."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.codes: dict[str, str] = {}  # auth_code -> code_challenge
        self.confirm_signup = True
        self.refreshed = 0
        self.fail_refresh = False

    def session(self, provider: str = "google", n: int = 1) -> dict[str, Any]:
        return {
            "access_token": f"access-{n}",
            "refresh_token": f"refresh-{n}",
            "expires_in": 3600,
            "user": user(provider=provider),
        }

    def issue(self, challenge: str) -> str:
        code = f"00000000-0000-4000-8000-{len(self.codes):012d}"
        self.codes[code] = challenge
        return code

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        self.calls.append((req.method, req.url.path, {**dict(req.url.params), **body}))
        assert req.headers.get("apikey") == ANON
        path, grant = req.url.path, req.url.params.get("grant_type")
        if path == "/auth/v1/token" and grant == "pkce":
            challenge = self.codes.pop(body.get("auth_code", ""), None)
            verifier = body.get("code_verifier", "")
            digest = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            if challenge is None or challenge != digest:
                return httpx.Response(
                    400, json={"error_code": "flow_state_not_found", "msg": "bad code"}
                )
            return httpx.Response(200, json=self.session())
        if path == "/auth/v1/token" and grant == "password":
            if body == {"email": "ana@example.com", "password": "correct-horse"}:
                return httpx.Response(200, json=self.session("email"))
            code = (
                "email_not_confirmed"
                if body.get("email") == "new@example.com"
                else "invalid_credentials"
            )
            return httpx.Response(
                400,
                json={
                    "error_code": code,
                    "msg": f"secret detail {body.get('password')}",
                },
            )
        if path == "/auth/v1/token" and grant == "refresh_token":
            if self.fail_refresh:
                return httpx.Response(
                    400, json={"error_code": "refresh_token_not_found"}
                )
            self.refreshed += 1
            return httpx.Response(200, json=self.session(n=1 + self.refreshed))
        if path == "/auth/v1/signup":
            if body.get("email") == "ana@example.com":
                return httpx.Response(
                    422, json={"error_code": "user_already_exists", "msg": "x"}
                )
            if self.confirm_signup:
                return httpx.Response(
                    200,
                    json={
                        "id": "u-2",
                        "email": body["email"],
                        "confirmation_sent_at": "now",
                    },
                )
            return httpx.Response(200, json=self.session("email"))
        if path == "/auth/v1/logout":
            return httpx.Response(204)
        return httpx.Response(404, json={})


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def fake() -> FakeGoTrue:
    return FakeGoTrue()


@pytest.fixture
def events() -> list:
    return []


@pytest.fixture
def clock() -> Clock:
    return Clock()


def make(
    tmp_path: Path,
    fake: FakeGoTrue,
    events: list,
    clock: Clock,
    configured: bool = True,
) -> au.AuthService:
    svc = au.AuthService(
        tmp_path / "state",
        lambda kind, data: events.append((kind, data)),
        client=httpx.Client(
            transport=httpx.MockTransport(fake), follow_redirects=False
        ),
        resolver=public,
        clock=clock,
        env={},
    )
    svc.set_port(PORT)
    if configured:
        svc.configure(URL, ANON)
    return svc


@pytest.fixture
def svc(tmp_path: Path, fake: FakeGoTrue, events: list, clock: Clock) -> au.AuthService:
    return make(tmp_path, fake, events, clock)


def challenge_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["code_challenge"][0]


# ---- configuration ---------------------------------------------------------------------


def test_not_configured_by_default(
    tmp_path: Path, fake: FakeGoTrue, events: list, clock: Clock
) -> None:
    s = make(tmp_path, fake, events, clock, configured=False)
    assert s.status()["configured"] is False and s.status()["signed_in"] is False
    with pytest.raises(au.AuthError) as err:
        s.start("google")
    assert err.value.status == 409 and "docs/accounts.md" in err.value.message


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("http://abcdefgh.supabase.co", ANON),  # plain http to a remote host
        ("https://user:pw@abcdefgh.supabase.co", ANON),
        ("https://abcdefgh.supabase.co/some/path", ANON),
        ("https://abcdefgh.supabase.co?x=1", ANON),
        ("https://10.0.0.5", ANON),  # private network
        ("not a url", ANON),
        (URL, "short"),
        (URL, "has space in it"),
        (URL, "k" * 3000),
    ],
)
def test_bad_configuration_is_refused(svc: au.AuthService, url: str, key: str) -> None:
    with pytest.raises(au.AuthError) as err:
        svc.configure(url, key)
    assert err.value.status == 400


def test_configuration_is_saved_private_and_env_wins(
    tmp_path: Path, fake: FakeGoTrue, events: list, clock: Clock
) -> None:
    s = make(tmp_path, fake, events, clock)
    path = tmp_path / "state" / "auth_config.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    other = au.AuthService(
        tmp_path / "state", lambda *a: None, client=httpx.Client(transport=httpx.MockTransport(fake)),
        resolver=public, clock=clock,
        env={"OMNIGROUP_AUTH_URL": "https://zzzzzzzz.supabase.co", "OMNIGROUP_AUTH_ANON_KEY": ANON},
    )  # fmt: skip
    assert (
        other.status()["host"] == "zzzzzzzz.supabase.co"
        and s.status()["host"] == "abcdefgh.supabase.co"
    )


# ---- OAuth with PKCE through the browser ------------------------------------------------


def test_start_builds_a_pkce_authorize_url(svc: au.AuthService) -> None:
    out = svc.start("github")
    parts = urlsplit(out["url"])
    q = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{URL}/auth/v1/authorize"
    assert q["provider"] == ["github"] and q["redirect_to"] == [CALLBACK]
    assert q["code_challenge_method"] == ["s256"] and len(q["code_challenge"][0]) == 43
    assert svc.status()["pending"] is True


def test_unknown_provider_is_refused(svc: au.AuthService) -> None:
    for bad in ("facebook", "", None, "google; drop"):
        with pytest.raises(au.AuthError) as err:
            svc.start(bad)
        assert err.value.status == 400


def test_full_oauth_round_trip(
    svc: au.AuthService, fake: FakeGoTrue, events: list, tmp_path: Path
) -> None:
    out = svc.start("google")
    code = fake.issue(challenge_of(out["url"]))
    status, html = svc.callback({"code": code})
    assert status == 200 and "Connecté" in html
    st = svc.status()
    assert st["signed_in"] is True and st["pending"] is False
    assert st["user"] == {
        "email": "ana@example.com",
        "name": "Ana Test",
        "provider": "google",
    }
    dumped = json.dumps(st) + html
    for secret in ("access-1", "refresh-1", ANON):
        assert secret not in dumped
    session_file = tmp_path / "state" / "auth_session.json"
    assert stat.S_IMODE(os.stat(session_file).st_mode) == 0o600
    assert "refresh-1" in session_file.read_text()
    assert events and events[-1][0] == "auth" and "refresh-1" not in json.dumps(events)


def test_a_code_made_for_another_flow_is_rejected(
    svc: au.AuthService, fake: FakeGoTrue
) -> None:
    """Login CSRF: an attacker's code is bound to the attacker's verifier, not ours."""
    svc.start("google")
    attacker_code = fake.issue("a" * 43)  # a challenge we know nothing about
    status, html = svc.callback({"code": attacker_code})
    assert status == 400 and svc.status()["signed_in"] is False
    assert attacker_code not in html


def test_callback_without_a_pending_flow_or_expired(
    svc: au.AuthService, fake: FakeGoTrue, clock: Clock
) -> None:
    assert svc.callback({"code": "00000000-0000-4000-8000-000000000001"})[0] == 400
    out = svc.start("google")
    code = fake.issue(challenge_of(out["url"]))
    clock.now += au.PENDING_TTL_S + 1
    status, html = svc.callback({"code": code})
    assert status == 400 and "expiré" in html and svc.status()["signed_in"] is False


def test_a_code_works_once(svc: au.AuthService, fake: FakeGoTrue) -> None:
    out = svc.start("google")
    code = fake.issue(challenge_of(out["url"]))
    assert svc.callback({"code": code})[0] == 200
    assert svc.callback({"code": code})[0] == 400


def test_failed_attempts_are_capped(svc: au.AuthService, fake: FakeGoTrue) -> None:
    out = svc.start("google")
    for _ in range(au.MAX_CALLBACK_ATTEMPTS):
        assert svc.callback({"code": "00000000-0000-4000-8000-0000000000ff"})[0] == 400
    good = fake.issue(challenge_of(out["url"]))
    assert svc.callback({"code": good})[0] == 400  # the flow was dropped


def test_callback_input_is_validated_and_never_reflected(svc: au.AuthService) -> None:
    svc.start("google")
    for q in (
        {},
        {"code": "<script>alert(1)</script>"},
        {"code": "x" * 500},
        {"code": ["a"]},
    ):
        status, html = svc.callback(q)
        assert status == 400 and "<script>" not in html
    status, html = svc.callback(
        {"error": "access_denied", "error_description": "<b>evil</b>"}
    )
    assert status == 400 and "<b>" not in html and "annulée" in html
    assert svc.status()["pending"] is False


# ---- e-mail + password ----------------------------------------------------------------


def test_password_sign_in(svc: au.AuthService, fake: FakeGoTrue) -> None:
    st = svc.password("signin", "ana@example.com", "correct-horse")
    assert st["signed_in"] is True and st["user"]["provider"] == "email"
    assert "correct-horse" not in json.dumps(st)


def test_wrong_password_gives_a_clean_message(svc: au.AuthService) -> None:
    with pytest.raises(au.AuthError) as err:
        svc.password("signin", "ana@example.com", "wrong-password")
    assert err.value.status == 422 and "incorrect" in err.value.message
    assert (
        "wrong-password" not in err.value.message
        and "secret detail" not in err.value.message
    )
    with pytest.raises(au.AuthError) as err:
        svc.password("signin", "new@example.com", "whatever-pass")
    assert "Confirmez" in err.value.message


def test_signup_waits_for_the_confirmation_email(
    svc: au.AuthService, fake: FakeGoTrue
) -> None:
    st = svc.password("signup", "new@example.com", "long-enough-pass")
    assert st["signed_in"] is False and "e-mail" in st["message"]
    call = next(c for c in fake.calls if c[1] == "/auth/v1/signup")
    assert (
        call[2]["code_challenge_method"] == "s256"
        and call[2]["redirect_to"] == CALLBACK
    )
    # the confirmation link comes back to the callback with a code bound to our verifier
    code = fake.issue(call[2]["code_challenge"])
    assert svc.callback({"code": code})[0] == 200 and svc.status()["signed_in"] is True


def test_signup_without_confirmation_signs_in(
    svc: au.AuthService, fake: FakeGoTrue
) -> None:
    fake.confirm_signup = False
    assert (
        svc.password("signup", "new@example.com", "long-enough-pass")["signed_in"]
        is True
    )


def test_existing_account_on_signup(svc: au.AuthService) -> None:
    with pytest.raises(au.AuthError) as err:
        svc.password("signup", "ana@example.com", "long-enough-pass")
    assert err.value.status == 409 and "existe déjà" in err.value.message


@pytest.mark.parametrize(
    ("mode", "email", "password"),
    [
        ("hack", "ana@example.com", "long-enough-pass"),
        ("signin", "not-an-email", "long-enough-pass"),
        ("signin", "a@b", "long-enough-pass"),
        ("signin", "ana@example.com\nBcc: x@y.z", "long-enough-pass"),
        ("signin", "a" * 300 + "@example.com", "long-enough-pass"),
        ("signup", "ana@example.com", "short"),
        ("signup", "ana@example.com", "p" * 200),
        ("signin", "ana@example.com", ""),
        ("signin", None, "long-enough-pass"),
        ("signin", "ana@example.com", 12345678),
    ],
)
def test_password_inputs_are_validated(
    svc: au.AuthService, mode: Any, email: Any, password: Any
) -> None:
    with pytest.raises(au.AuthError) as err:
        svc.password(mode, email, password)
    assert err.value.status == 400


def test_password_attempts_are_rate_limited(svc: au.AuthService, clock: Clock) -> None:
    for _ in range(au.MAX_PASSWORD_ATTEMPTS):
        with pytest.raises(au.AuthError):
            svc.password("signin", "ana@example.com", "wrong-password")
    with pytest.raises(au.AuthError) as err:
        svc.password("signin", "ana@example.com", "correct-horse")
    assert err.value.status == 429
    clock.now += au.ATTEMPT_WINDOW_S + 1
    assert (
        svc.password("signin", "ana@example.com", "correct-horse")["signed_in"] is True
    )


# ---- session ----------------------------------------------------------------------------


def signed_in(svc: au.AuthService) -> None:
    svc.password("signin", "ana@example.com", "correct-horse")


def test_the_session_survives_a_restart(
    svc: au.AuthService, tmp_path: Path, fake: FakeGoTrue, events: list, clock: Clock
) -> None:
    signed_in(svc)
    again = make(tmp_path, fake, events, clock)
    assert (
        again.status()["signed_in"] is True
        and again.status()["user"]["email"] == "ana@example.com"
    )


def test_access_token_is_refreshed_and_rotated(
    svc: au.AuthService, fake: FakeGoTrue, clock: Clock, tmp_path: Path
) -> None:
    signed_in(svc)
    assert svc.access_token() == "access-1"
    clock.now += 3600  # expired
    assert svc.access_token() == "access-2"
    assert "refresh-2" in (tmp_path / "state" / "auth_session.json").read_text()
    assert svc.access_token() == "access-2" and fake.refreshed == 1


def test_a_dead_refresh_token_signs_out_locally(
    svc: au.AuthService, fake: FakeGoTrue, clock: Clock, tmp_path: Path
) -> None:
    signed_in(svc)
    fake.fail_refresh = True
    clock.now += 3600
    assert svc.access_token() is None
    assert (
        svc.status()["signed_in"] is False
        and not (tmp_path / "state" / "auth_session.json").exists()
    )


def test_sign_out_revokes_and_forgets(
    svc: au.AuthService, fake: FakeGoTrue, tmp_path: Path, events: list
) -> None:
    signed_in(svc)
    st = svc.signout()
    assert (
        st["signed_in"] is False
        and not (tmp_path / "state" / "auth_session.json").exists()
    )
    assert any(c[1] == "/auth/v1/logout" for c in fake.calls)
    assert events[-1][0] == "auth"


def test_sign_out_still_works_when_the_service_is_down(
    svc: au.AuthService, tmp_path: Path
) -> None:
    signed_in(svc)
    svc._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))
        )
    )
    assert svc.signout()["signed_in"] is False


def test_a_rebinding_hostname_is_refused_before_any_call(
    tmp_path: Path, fake: FakeGoTrue, events: list, clock: Clock
) -> None:
    s = make(tmp_path, fake, events, clock)
    s._resolver = lambda h, p, *a, **k: [(2, 1, 6, "", ("10.0.0.9", p))]
    with pytest.raises(au.AuthError):
        s.password("signin", "ana@example.com", "correct-horse")
    assert fake.calls == []


def test_provider_errors_never_leak_server_text(
    svc: au.AuthService, fake: FakeGoTrue
) -> None:
    svc._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(500, text="stack trace with SECRET-TOKEN")
        )
    )
    with pytest.raises(au.AuthError) as err:
        svc.password("signin", "ana@example.com", "correct-horse")
    assert "SECRET-TOKEN" not in err.value.message and err.value.status == 502
