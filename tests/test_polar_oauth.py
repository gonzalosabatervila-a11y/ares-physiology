"""OAuth de Polar: canje de código y renovación, con la red simulada.
No abre navegador ni servidor real: eso se prueba a mano mañana con `ares polar-auth`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ares.connectors import polar_oauth as oauth


def make_http(status: int, body: dict, seen: list) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_authorize_envia_basic_auth_y_canjea_el_codigo(monkeypatch):
    seen: list[httpx.Request] = []
    http = make_http(
        200, {"access_token": "tok-a", "refresh_token": "ref-a", "expires_in": 43200}, seen
    )
    monkeypatch.setattr(oauth, "_wait_for_code", lambda redirect_uri, timeout_s=300.0: "code-123")

    before = datetime.now(UTC)
    tokens = oauth.authorize("client-id", "client-secret", "http://localhost:8765/callback", http)

    assert tokens.access_token == "tok-a"
    assert tokens.refresh_token == "ref-a"
    assert (
        timedelta(hours=11, minutes=59)
        < (tokens.expires_at - before)
        < timedelta(hours=12, minutes=1)
    )

    req = seen[0]
    assert req.url == httpx.URL("https://auth.polar.com/oauth/token")
    body = req.content.decode()
    assert "grant_type=authorization_code" in body
    assert "code=code-123" in body
    assert req.headers["Authorization"].startswith("Basic ")


def test_authorize_token_endpoint_error_lanza_oautherror(monkeypatch):
    seen: list[httpx.Request] = []
    http = make_http(400, {"error": "invalid_grant"}, seen)
    monkeypatch.setattr(oauth, "_wait_for_code", lambda redirect_uri, timeout_s=300.0: "code-123")
    with pytest.raises(oauth.OAuthError, match="400"):
        oauth.authorize("client-id", "client-secret", "http://localhost:8765/callback", http)


def test_refresh_envia_refresh_token():
    seen: list[httpx.Request] = []
    http = make_http(
        200, {"access_token": "tok-b", "refresh_token": "ref-b", "expires_in": 43200}, seen
    )
    tokens = oauth.refresh("client-id", "client-secret", "ref-a", http)
    assert tokens.access_token == "tok-b"
    body = seen[0].content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=ref-a" in body


def test_needs_refresh_umbral_60_min():
    now = datetime.now(UTC)
    assert oauth.needs_refresh(now + timedelta(minutes=30)) is True
    assert oauth.needs_refresh(now + timedelta(hours=5)) is False
