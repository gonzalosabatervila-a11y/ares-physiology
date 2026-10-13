"""Autorización OAuth2 con la API v2 de WHOOP (arranque, una sola vez: `ares whoop-auth`).

Flujo de código de autorización con un servidor local efímero en `WHOOP_REDIRECT_URI`
(por defecto http://localhost:8765/callback, que debe estar registrada exacta en el panel de
desarrolladores). Según developer.whoop.com (verificado el 02/10/2026, fe de erratas v0.3):

- autorización en api.prod.whoop.com/oauth/oauth2/auth; token en .../oauth/oauth2/token;
- `state` de exactamente 8 caracteres;
- `offline` es necesario para recibir refresh token;
- el refresh token es de un solo uso y renovar invalida también el access token anterior;
- la renovación lleva client_id, client_secret y scope=offline en el cuerpo del formulario.

Permisos mínimos aprobados: sin read:profile ni read:body_measurement.
Los errores llevan el código HTTP y el `error`/`error_description` de WHOOP, nunca tokens
ni el cuerpo completo de la respuesta.
"""

from __future__ import annotations

import secrets
import string
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
SCOPES = "read:recovery read:sleep read:cycles read:workout offline"
STATE_LEN = 8
DEFAULT_EXPIRES_IN = 3600  # el valor de ejemplo de WHOOP; manda siempre el que devuelva


class OAuthError(RuntimeError):
    """Fallo de autorización o de renovación. `status` y `error` vienen de WHOOP."""

    def __init__(self, message: str, *, status: int | None = None, error: str | None = None):
        super().__init__(message)
        self.status = status
        self.error = error


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime  # UTC

    def __repr__(self) -> str:  # que un log o un traceback nunca enseñe los tokens
        return f"TokenSet(expires_at={self.expires_at.isoformat()})"


def new_state() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(STATE_LEN))


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    """Atiende una única petición al redirect_uri y guarda lo recibido."""

    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802 (nombre fijado por BaseHTTPRequestHandler)
        query = parse_qs(urlparse(self.path).query)

        def first(key: str) -> str | None:
            values = query.get(key)
            return values[0] if values else None

        self.server.state_received = first("state")
        self.server.code = first("code")
        self.server.error = first("error")
        self.server.error_description = first("error_description")
        body = (
            "Autorizacion completada. Puedes cerrar esta pestana y volver a la terminal."
            if self.server.code
            else "Fallo la autorizacion. Vuelve a la terminal para ver el motivo."
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # la URL lleva el código: no se registra
        pass


class _CallbackServer(HTTPServer):
    code: str | None
    error: str | None
    error_description: str | None
    state_received: str | None

    def __init__(self, *a: Any, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.code = None
        self.error = None
        self.error_description = None
        self.state_received = None


def _wait_for_code(
    client_id: str,
    redirect_uri: str,
    open_browser: Callable[[str], object],
    timeout_s: float,
) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http":
        raise OAuthError(
            f"El servidor local solo atiende http://, y la URI configurada es {parsed.scheme}://. "
            "Revisa WHOOP_REDIRECT_URI."
        )
    host, port = parsed.hostname or "localhost", parsed.port or 80
    state = new_state()
    url = authorize_url(client_id, redirect_uri, state)
    with _CallbackServer((host, port), _CallbackHandler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        server.timeout = timeout_s
        thread.start()
        open_browser(url)
        thread.join(timeout=timeout_s)
        if thread.is_alive():
            raise OAuthError(f"No llegó respuesta en {timeout_s:.0f} s. Abre manualmente: {url}")
    if server.error:
        detail = f" — {server.error_description}" if server.error_description else ""
        raise OAuthError(
            f"WHOOP rechazó la autorización: {server.error}{detail}", error=server.error
        )
    if not server.code:
        raise OAuthError("No se recibió código de autorización.")
    if server.state_received != state:
        raise OAuthError("El 'state' devuelto no coincide: posible interferencia externa.")
    return server.code


def _raise_for_token_error(resp: httpx.Response, what: str) -> None:
    if resp.status_code == 200:
        return
    error = description = None
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        description = body.get("error_description")
    detail = " · ".join(str(x)[:200] for x in (error, description) if x) or "sin detalle"
    raise OAuthError(
        f"{what} fallida: HTTP {resp.status_code} · {detail}",
        status=resp.status_code,
        error=str(error) if error else None,
    )


def _token_set(body: dict[str, Any]) -> TokenSet:
    """El refresh token es obligatorio: WHOOP rota el par en cada renovación, así que una
    respuesta sin él dejaría la cuenta sin forma de renovar (el anterior ya no vale)."""
    access = body.get("access_token")
    refresh_tok = body.get("refresh_token")
    if not access:
        raise OAuthError("La respuesta de WHOOP no incluye access_token.")
    if not refresh_tok:
        raise OAuthError(
            "La respuesta de WHOOP no incluye refresh_token: ¿falta el permiso offline?"
        )
    expires_in = int(body.get("expires_in") or DEFAULT_EXPIRES_IN)
    return TokenSet(
        access_token=access,
        refresh_token=refresh_tok,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


def _post_token(http: httpx.Client | None, data: dict[str, str]) -> httpx.Response:
    client = http or httpx.Client(timeout=30.0)
    return client.post(
        TOKEN_URL,
        data=data,
        headers={"Accept": "application/json"},
    )


def authorize(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    *,
    http: httpx.Client | None = None,
    open_browser: Callable[[str], object] = webbrowser.open,
    timeout_s: float = 300.0,
) -> TokenSet:
    """Autorización inicial completa: abre el navegador, espera el código y lo canjea."""
    code = _wait_for_code(client_id, redirect_uri, open_browser, timeout_s)
    resp = _post_token(
        http,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    _raise_for_token_error(resp, "Canje del código")
    return _token_set(resp.json())


def refresh(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    http: httpx.Client | None = None,
) -> TokenSet:
    """Renueva el par. Quien llama debe tener el bloqueo de whoop_tokens y guardar el
    resultado antes de usarlo: el refresh token recibido es ya el único válido."""
    resp = _post_token(
        http,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "offline",
        },
    )
    _raise_for_token_error(resp, "Renovación")
    return _token_set(resp.json())
