"""Account routes on a real daemon: widget-token routes, the public browser callback,
HTML replies, and the guarantees (no token ever returned, no reflected input)."""

from __future__ import annotations

import http.client
import json
from pathlib import Path

import httpx

from omniscient.group import auth as au
from tests.group_support import Daemon, daemon
from tests.platform_marks import WINDOWS

__all__ = ["daemon"]  # the fixture

URL = "https://abcdefgh.supabase.co"
ANON = "eyJhbGciOiJIUzI1NiJ9.anon-public-key.sig"


def public(host: str, port: int = 443, *a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", port))]


def tokens(req: httpx.Request) -> httpx.Response:
    body = json.loads(req.content or b"{}")
    if (
        req.url.params.get("grant_type") == "password"
        and body.get("password") == "correct-horse"
    ):
        return httpx.Response(
            200,
            json={
                "access_token": "ACCESS-SECRET", "refresh_token": "REFRESH-SECRET", "expires_in": 3600,
                "user": {"id": "u", "email": "ana@example.com", "app_metadata": {"provider": "email"}},
            },
        )  # fmt: skip
    if req.url.path == "/auth/v1/otp":
        return httpx.Response(200, json={})
    if req.url.path == "/auth/v1/verify":
        if body.get("token") == "123456":
            return httpx.Response(
                200,
                json={
                    "access_token": "ACCESS-SECRET", "refresh_token": "REFRESH-SECRET", "expires_in": 3600,
                    "user": {"id": "u", "email": body["email"], "app_metadata": {"provider": "email"}},
                },
            )  # fmt: skip
        return httpx.Response(403, json={"error_code": "otp_expired"})
    return httpx.Response(400, json={"error_code": "invalid_credentials"})


def configure(d: Daemon) -> au.AuthService:
    svc = d.server.app.auth
    svc._client = httpx.Client(transport=httpx.MockTransport(tokens))
    svc._resolver = public
    svc._env = {}
    svc.configure(URL, ANON)
    return svc


def raw_get(d: Daemon, path: str) -> tuple[int, str, http.client.HTTPResponse]:
    conn = d.conn()
    conn.request("GET", path)
    resp = conn.getresponse()
    text = resp.read().decode()
    conn.close()
    return resp.status, text, resp


def unconfigured(d: Daemon) -> None:
    svc = d.server.app.auth
    svc._env, svc._defaults = {}, None  # a daemon without the shipped default project


def test_status_needs_the_widget_token(daemon: Daemon) -> None:
    unconfigured(daemon)
    assert daemon.call("GET", "/auth", auth=False)[0] == 401
    status, body, _ = daemon.call("GET", "/auth")
    assert status == 200 and body["configured"] is False and body["signed_in"] is False


def test_start_and_password_need_the_widget_token(daemon: Daemon) -> None:
    for path in ("/auth/start", "/auth/password", "/auth/signout"):
        assert daemon.call("POST", path, {}, auth=False)[0] == 401
        assert (
            daemon.call("POST", path, {}, auth="hook")[0] == 403
        )  # the hook credential is not enough


def test_not_configured_is_a_409(daemon: Daemon) -> None:
    unconfigured(daemon)
    status, body, _ = daemon.call("POST", "/auth/start", {"provider": "google"})
    assert status == 409 and "docs/accounts.md" in body["error"]


def test_start_returns_the_authorize_url_with_the_daemon_port(daemon: Daemon) -> None:
    configure(daemon)
    status, body, _ = daemon.call("POST", "/auth/start", {"provider": "github"})
    assert status == 200 and body["url"].startswith(f"{URL}/auth/v1/authorize?")
    assert f"127.0.0.1%3A{daemon.server.port}%2Fauth%2Fcallback" in body["url"]
    assert daemon.call("POST", "/auth/start", {"provider": "facebook"})[0] == 400


def test_password_sign_in_never_returns_a_token(daemon: Daemon) -> None:
    configure(daemon)
    status, body, _ = daemon.call(
        "POST",
        "/auth/password",
        {"mode": "signin", "email": "ana@example.com", "password": "correct-horse"},
    )
    assert (
        status == 200
        and body["signed_in"] is True
        and body["user"]["email"] == "ana@example.com"
    )
    everything = json.dumps(body) + json.dumps(daemon.call("GET", "/auth")[1])
    assert (
        "SECRET" not in everything
        and ANON not in everything
        and "correct-horse" not in everything
    )
    status, body, _ = daemon.call(
        "POST",
        "/auth/password",
        {"mode": "signin", "email": "ana@example.com", "password": "wrong-password"},
    )
    assert status == 422 and "incorrect" in body["error"]
    assert daemon.call("POST", "/auth/signout", {})[1]["signed_in"] is False


def test_the_callback_is_public_html_with_strict_headers(daemon: Daemon) -> None:
    configure(daemon)
    status, text, resp = raw_get(
        daemon, "/auth/callback?code=00000000-0000-4000-8000-000000000001"
    )
    assert status == 400 and text.startswith(
        "<!doctype html>"
    )  # no flow pending: expired page
    assert resp.getheader("Content-Type").startswith("text/html")
    assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    assert (
        resp.getheader("X-Frame-Options") == "DENY"
        and resp.getheader("Referrer-Policy") == "no-referrer"
    )
    assert resp.getheader("Cache-Control") == "no-store"


def test_the_callback_reflects_nothing(daemon: Daemon) -> None:
    configure(daemon)
    daemon.call("POST", "/auth/start", {"provider": "google"})
    _, text, _ = raw_get(
        daemon,
        "/auth/callback?error=access_denied&error_description=%3Cscript%3Ealert(1)%3C/script%3E",
    )
    assert "<script>" not in text and "alert" not in text


def test_the_callback_is_refused_for_a_foreign_host(daemon: Daemon) -> None:
    conn = daemon.conn()
    conn.request("GET", "/auth/callback?code=x", headers={"Host": "evil.example"})
    assert conn.getresponse().status == 421


def test_the_confirmation_landing_page(daemon: Daemon) -> None:
    status, text, resp = raw_get(daemon, "/auth/confirmed")
    assert (
        status == 200
        and "confirmé" in text
        and resp.getheader("Content-Type").startswith("text/html")
    )


def test_the_callback_only_answers_get(daemon: Daemon) -> None:
    assert daemon.call("POST", "/auth/callback", {}, auth=False)[0] in (404, 405)


def test_files_are_private(daemon: Daemon, tmp_path: Path) -> None:
    configure(daemon)
    daemon.call(
        "POST",
        "/auth/password",
        {"mode": "signin", "email": "ana@example.com", "password": "correct-horse"},
    )
    import os
    import stat

    for name in () if WINDOWS else ("auth_config.json", "auth_session.json"):
        assert (
            stat.S_IMODE(os.stat(tmp_path / ".omniscient" / name).st_mode) == 0o600
        ), name


def test_a_wrong_code_while_a_flow_is_pending_gets_the_failure_page(
    daemon: Daemon,
) -> None:
    configure(daemon)
    daemon.call("POST", "/auth/start", {"provider": "google"})
    status, text, _ = raw_get(
        daemon, "/auth/callback?code=00000000-0000-4000-8000-000000000001"
    )
    assert status == 400 and text.startswith("<!doctype html>") and "impossible" in text
    assert daemon.call("GET", "/auth")[1]["signed_in"] is False


# ---- e-mail code: signs the widget in AND pairs it (no desktop code) -----------------------


def test_email_start_is_public_and_sends_nothing_back(daemon: Daemon) -> None:
    configure(daemon)
    status, body, _ = daemon.call(
        "POST", "/auth/email/start", {"email": "ana@example.com"}, auth=False
    )
    assert status == 200 and "token" not in json.dumps(body)


def test_email_verify_mints_a_widget_token_that_works(daemon: Daemon) -> None:
    configure(daemon)
    daemon.call("POST", "/auth/email/start", {"email": "ana@example.com"}, auth=False)
    status, body, _ = daemon.call(
        "POST", "/auth/email/verify",
        {"email": "ana@example.com", "code": "123456", "client_name": "PC"}, auth=False,
    )  # fmt: skip
    assert status == 200 and body["user"]["email"] == "ana@example.com"
    token = body["token"]
    assert "ACCESS-SECRET" not in json.dumps(
        body
    ) and "REFRESH-SECRET" not in json.dumps(body)
    conn = daemon.conn()
    conn.request("GET", "/auth", headers={"Authorization": f"Bearer {token}"})
    resp = conn.getresponse()
    assert resp.status == 200 and json.loads(resp.read())["signed_in"] is True


def test_email_verify_wrong_code_mints_nothing(daemon: Daemon) -> None:
    configure(daemon)
    status, body, _ = daemon.call(
        "POST", "/auth/email/verify", {"email": "ana@example.com", "code": "000000"}, auth=False
    )  # fmt: skip
    assert status == 422 and "token" not in body


def test_email_routes_validate_their_input(daemon: Daemon) -> None:
    configure(daemon)
    assert (
        daemon.call("POST", "/auth/email/start", {"email": "nope"}, auth=False)[0]
        == 400
    )
    bad = {"email": "ana@example.com", "code": "abc"}
    assert daemon.call("POST", "/auth/email/verify", bad, auth=False)[0] == 400
