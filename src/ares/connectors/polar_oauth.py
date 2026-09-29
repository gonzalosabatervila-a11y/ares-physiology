"""Autorización OAuth2 con Polar AccessLink v4 (arranque, una sola vez).

Flujo de código de autorización con un servidor local efímero en el `redirect_uri`
configurado (por defecto http://localhost:8765/callback). Documentación oficial:
https://www.polar.com/polar-api-v4/ — autorización en auth.polar.com/oauth/authorize,
token en auth.polar.com/oauth/token (Basic con client_id:client_secret).

Scopes pedidos: nightly_recharge:read sleep:read ppi_data:read continuous_samples:read
skin_contact:read activity:read devices:read (Implementation Plan v0.2 FINAL, §5).
"""

from __future__ import annotations

import base64
import secrets
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URL = "https://auth.polar.com/oauth/authorize"
TOKEN_URL = "https://auth.polar.com/oauth/token"
SCOPES = (
    "nightly_recharge:read sleep:read ppi_data:read continuous_samples:read "
    "skin_contact:read activity:read devices:read"
)


class OAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime  # UTC


class _CallbackHandler(BaseHTTPRequestHandler):
    """Atiende una única petición al redirect_uri y guarda el `code` recibido."""

    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802 (nombre fijado por BaseHTTPRequestHandler)
        query = parse_qs(urlparse(self.path).query)

        def first(key: str) -> str | None:
            values = query.get(key)
            return values[0] if values else None

        self.server.state_received = first("state")
        self.server.code = first("code")
        self.server.error = first("error")
        body = (
            "Autorizacion completada. Puedes cerrar esta pestana y volver a la terminal."
            if self.server.code
            else f"Fallo la autorizacion: {self.server.error or 'sin código'}."
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silenciar el log por defecto
        pass


class _CallbackServer(HTTPServer):
    code: str | None
    error: str | None
    state_received: str | None

    def __init__(self, *a: object, **kw: object) -> None:
        super().__init__(*a, **kw)  # type: ignore[arg-type]
        self.code = None
        self.error = None
        self.state_received = None


def _wait_for_code(redirect_uri: str, timeout_s: float = 300.0) -> str:
    parsed = urlparse(redirect_uri)
    host, port = parsed.hostname or "localhost", parsed.port or 8765
    server = _CallbackServer((host, port), _CallbackHandler)
    expected_state = secrets.token_urlsafe(16)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    params = {
        "response_type": "code",
        "client_id": _pending_client_id[0],
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": expected_state,
    }
    url = f"{AUTH_URL}?{urlencode(params)}"
    webbrowser.open(url)
    thread.join(timeout=timeout_s)
    if thread.is_alive():
        raise OAuthError(f"No llegó respuesta en {timeout_s:.0f}s. Abre manualmente: {url}")
    if server.error:
        raise OAuthError(f"Polar rechazó la autorización: {server.error}")
    if not server.code:
        raise OAuthError("No se recibió código de autorización.")
    if server.state_received != expected_state:
        raise OAuthError("El 'state' devuelto no coincide: posible interferencia externa.")
    return server.code


# Truco simple para pasar el client_id a _wait_for_code sin cambiar su firma pública.
_pending_client_id: list[str] = [""]


def _basic_auth_header(client_id: str, client_secret: str) -> dict[str, str]:
    raw = f"{client_id}:{client_secret}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _token_set_from_response(body: dict, fallback_refresh: str | None = None) -> TokenSet:
    """Convierte la respuesta del endpoint de token. `expires_in` viene en segundos;
    la documentación indica 12 h, pero se respeta siempre el valor que devuelva Polar.
    Si la respuesta de una renovación no trae `refresh_token`, se conserva el anterior."""
    expires_in = int(body.get("expires_in", 3600 * 12))
    refresh_token = body.get("refresh_token") or fallback_refresh
    if not refresh_token:
        raise OAuthError("La respuesta de Polar no incluye refresh_token.")
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


def authorize(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http: httpx.Client | None = None,
) -> TokenSet:
    """Autorización inicial completa: abre el navegador, espera el código,
    lo canjea por tokens. Se ejecuta una sola vez (`ares polar-auth`)."""
    _pending_client_id[0] = client_id
    code = _wait_for_code(redirect_uri)
    client = http or httpx.Client(timeout=30.0)
    resp = client.post(
        TOKEN_URL,
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        headers=_basic_auth_header(client_id, client_secret)
        | {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if resp.status_code != 200:
        raise OAuthError(f"Canje de código fallido: HTTP {resp.status_code} — {resp.text[:300]}")
    return _token_set_from_response(resp.json())


def refresh(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    http: httpx.Client | None = None,
) -> TokenSet:
    """Renueva el access token. Se llama cuando faltan <60 min para caducar (§6)."""
    client = http or httpx.Client(timeout=30.0)
    resp = client.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers=_basic_auth_header(client_id, client_secret)
        | {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if resp.status_code != 200:
        raise OAuthError(f"Renovación fallida: HTTP {resp.status_code} — {resp.text[:300]}")
    return _token_set_from_response(resp.json(), fallback_refresh=refresh_token)


def needs_refresh(expires_at: datetime, margin: timedelta = timedelta(minutes=60)) -> bool:
    return datetime.now(UTC) + margin >= expires_at
