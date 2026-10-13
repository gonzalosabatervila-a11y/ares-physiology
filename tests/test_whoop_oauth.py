"""OAuth de WHOOP: permisos mínimos, state de 8 caracteres, credenciales en el cuerpo,
scope=offline al renovar y errores con código HTTP pero sin tokens."""

from __future__ import annotations

import socket
import string
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest

from ares.connectors import whoop_oauth


def token_http(
    body: dict, status: int = 200
) -> tuple[httpx.Client, list[tuple[httpx.Request, dict[str, str]]]]:
    seen: list[tuple[httpx.Request, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request, dict(parse_qsl(request.content.decode()))))
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_state_de_ocho_caracteres_alfanumericos():
    states = {whoop_oauth.new_state() for _ in range(50)}
    assert len(states) > 45  # aleatorio
    for st in states:
        assert len(st) == 8 and set(st) <= set(string.ascii_letters + string.digits)


def test_la_url_pide_solo_los_permisos_minimos():
    url = whoop_oauth.authorize_url("cid", "http://localhost:8765/callback", "abcd1234")
    assert url.startswith("https://api.prod.whoop.com/oauth/oauth2/auth?")
    q = parse_qs(urlparse(url).query)
    assert q["scope"] == ["read:recovery read:sleep read:cycles read:workout offline"]
    assert "read:profile" not in url and "read:body_measurement" not in url
    assert q["response_type"] == ["code"] and q["state"] == ["abcd1234"]
    assert q["redirect_uri"] == ["http://localhost:8765/callback"]


def test_renovar_manda_credenciales_en_el_cuerpo_y_scope_offline():
    http, seen = token_http({"access_token": "a2", "refresh_token": "r2", "expires_in": 3600})
    before = datetime.now(UTC)
    tokens = whoop_oauth.refresh("cid", "csec", "r1", http=http)
    ((req, form),) = seen
    assert str(req.url) == "https://api.prod.whoop.com/oauth/oauth2/token"
    assert "authorization" not in req.headers
    assert form == {
        "grant_type": "refresh_token",
        "refresh_token": "r1",
        "client_id": "cid",
        "client_secret": "csec",
        "scope": "offline",
    }
    assert (tokens.access_token, tokens.refresh_token) == ("a2", "r2")
    assert before + timedelta(seconds=3590) < tokens.expires_at
    assert "a2" not in repr(tokens) and "r2" not in repr(tokens)


def test_una_renovacion_sin_refresh_token_es_un_error():
    http, _ = token_http({"access_token": "a2", "expires_in": 3600})
    with pytest.raises(whoop_oauth.OAuthError, match="refresh_token"):
        whoop_oauth.refresh("cid", "csec", "r1", http=http)


def test_el_error_lleva_codigo_y_motivo_de_whoop_pero_no_tokens():
    http, _ = token_http(
        {"error": "invalid_client", "error_description": "Client authentication failed"},
        status=401,
    )
    with pytest.raises(whoop_oauth.OAuthError) as info:
        whoop_oauth.refresh("cid", "csec-secreto", "r1-secreto", http=http)
    msg = str(info.value)
    assert "HTTP 401" in msg and "invalid_client" in msg
    assert "secreto" not in msg
    assert (info.value.status, info.value.error) == (401, "invalid_client")


def test_un_error_sin_json_no_vuelca_el_cuerpo():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>access_token=filtrado</html>")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(whoop_oauth.OAuthError) as info:
        whoop_oauth.refresh("cid", "csec", "r1", http=http)
    assert "filtrado" not in str(info.value) and info.value.status == 500


def _simular_navegador(params: dict[str, str]):
    """Hace de navegador: en vez de abrir la URL, llama al callback local como haría WHOOP."""

    def abrir(url: str) -> None:
        q = parse_qs(urlparse(url).query)
        redirect = q["redirect_uri"][0]
        datos = {k: v.replace("{state}", q["state"][0]) for k, v in params.items()}

        def llamar() -> None:
            httpx.get(redirect, params=datos, timeout=5)

        threading.Thread(target=llamar, daemon=True).start()

    return abrir


def test_flujo_completo_canjea_el_codigo_con_las_credenciales_en_el_cuerpo():
    redirect = f"http://127.0.0.1:{free_port()}/callback"
    http, seen = token_http({"access_token": "a1", "refresh_token": "r1", "expires_in": 3600})
    tokens = whoop_oauth.authorize(
        "cid",
        "csec",
        redirect,
        http=http,
        open_browser=_simular_navegador({"code": "c0de", "state": "{state}"}),
        timeout_s=10,
    )
    ((req, form),) = seen
    assert "authorization" not in req.headers
    assert form == {
        "grant_type": "authorization_code",
        "code": "c0de",
        "redirect_uri": redirect,
        "client_id": "cid",
        "client_secret": "csec",
    }
    assert tokens.refresh_token == "r1"


def test_un_state_distinto_se_rechaza():
    redirect = f"http://127.0.0.1:{free_port()}/callback"
    http, seen = token_http({})
    with pytest.raises(whoop_oauth.OAuthError, match="state"):
        whoop_oauth.authorize(
            "cid",
            "csec",
            redirect,
            http=http,
            open_browser=_simular_navegador({"code": "c0de", "state": "otro1234"}),
            timeout_s=10,
        )
    assert seen == []  # no se canjea nada


def test_el_rechazo_de_whoop_en_el_callback_se_explica():
    redirect = f"http://127.0.0.1:{free_port()}/callback"
    http, _ = token_http({})
    with pytest.raises(whoop_oauth.OAuthError, match="invalid_scope") as info:
        whoop_oauth.authorize(
            "cid",
            "csec",
            redirect,
            http=http,
            open_browser=_simular_navegador(
                {"error": "invalid_scope", "error_description": "bad scope", "state": "{state}"}
            ),
            timeout_s=10,
        )
    assert info.value.error == "invalid_scope"


def test_una_redireccion_https_avisa_en_vez_de_esperar():
    with pytest.raises(whoop_oauth.OAuthError, match="https"):
        whoop_oauth.authorize(
            "cid", "csec", "https://localhost:8765/callback", open_browser=lambda u: None
        )
