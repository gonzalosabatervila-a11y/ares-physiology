"""Token de acceso de WHOOP: lo lee del almacén de secretos, lo renueva si está por caducar
y guarda el par rotado antes de devolverlo.

Reglas (fe de erratas v0.3, D3):
- margen de renovación de 5 min sobre el `expires_in` real (los tokens duran ~1 h);
- toda lectura-renovación-escritura va dentro de un lockfile portable compartido por
  `ares serve` y el CLI; dentro del bloqueo se vuelve a leer el almacén, por si otro
  proceso acaba de renovar;
- el par nuevo se guarda antes de usarlo, empezando por el refresh token;
- ante un 401, una sola renovación forzada y un único reintento.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .. import config
from ..locks import LockTimeout, file_lock
from . import whoop_oauth

REFRESH_MARGIN = timedelta(minutes=5)
LOCK_FILE = "whoop_token.lock"
LOCK_TIMEOUT_S = 60.0

Getter = Callable[[str], str | None]
Setter = Callable[[str, str], None]


class TokenError(RuntimeError):
    """Falta alguna credencial o autorización; el mensaje dice qué hacer."""


def lock_path(data_dir: Path) -> Path:
    return data_dir / LOCK_FILE


def save_tokens(tokens: whoop_oauth.TokenSet, put: Setter) -> None:
    """Primero el refresh token: es el único que, si se perdiera, obligaría a reautorizar."""
    put("whoop_refresh_token", tokens.refresh_token)
    put("whoop_access_token", tokens.access_token)
    put("whoop_token_expiry", tokens.expires_at.isoformat())


def _parse_expiry(raw: str) -> datetime:
    """Una caducidad ilegible cuenta como caducada: se renueva y se guarda una buena."""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def get_access_token(
    data_dir: Path,
    *,
    http: httpx.Client | None = None,
    secret_getter: Getter | None = None,
    secret_setter: Setter | None = None,
    now: Callable[[], datetime] | None = None,
    reject: str | None = None,
    lock_timeout_s: float = LOCK_TIMEOUT_S,
) -> str:
    """Devuelve un access token válido. `reject` es un token que WHOOP acaba de rechazar con
    401: se renueva salvo que otro proceso ya lo haya sustituido mientras tanto."""
    # Se resuelven aquí y no como valores por defecto, para que un monkeypatch de
    # `config.get_secret` se respete (mismo motivo que en runner.py).
    get = secret_getter or config.get_secret
    put = secret_setter or config.set_secret
    clock = now or (lambda: datetime.now(UTC))

    try:
        with file_lock(lock_path(data_dir), timeout_s=lock_timeout_s):
            client_id = get("whoop_client_id")
            client_secret = get("whoop_client_secret")
            if not client_id or not client_secret:
                raise TokenError(
                    "Faltan las credenciales del cliente de WHOOP: ejecuta ares whoop-auth"
                )
            access = get("whoop_access_token")
            refresh_tok = get("whoop_refresh_token")
            expiry_raw = get("whoop_token_expiry")
            if not access or not refresh_tok or not expiry_raw:
                raise TokenError("Este equipo no está autorizado en WHOOP: ejecuta ares whoop-auth")

            fresh = clock() + REFRESH_MARGIN < _parse_expiry(expiry_raw)
            if fresh and (reject is None or access != reject):
                return access

            try:
                tokens = whoop_oauth.refresh(client_id, client_secret, refresh_tok, http=http)
            except whoop_oauth.OAuthError as exc:
                raise TokenError(
                    f"{exc}. El refresh token ya no sirve: ejecuta ares whoop-auth"
                ) from exc
            save_tokens(tokens, put)
            return tokens.access_token
    except LockTimeout as exc:
        raise TokenError(str(exc)) from exc


def call_with_token(
    send: Callable[[str], httpx.Response],
    data_dir: Path,
    *,
    http: httpx.Client | None = None,
    secret_getter: Getter | None = None,
    secret_setter: Setter | None = None,
    now: Callable[[], datetime] | None = None,
) -> httpx.Response:
    """Llama a la API con un token válido. Si WHOOP responde 401, renueva una vez y reintenta;
    un segundo 401 ya no se reintenta (credenciales o permisos rotos: hace falta whoop-auth).
    `http` es el cliente del endpoint de token, no el de la API."""

    def token(reject: str | None = None) -> str:
        return get_access_token(
            data_dir,
            http=http,
            secret_getter=secret_getter,
            secret_setter=secret_setter,
            now=now,
            reject=reject,
        )

    first = token()
    resp = send(first)
    if resp.status_code != 401:
        return resp
    resp = send(token(reject=first))
    if resp.status_code == 401:
        raise TokenError(
            "WHOOP rechaza el token incluso recién renovado (HTTP 401): "
            "revisa los permisos del cliente y ejecuta ares whoop-auth"
        )
    return resp
