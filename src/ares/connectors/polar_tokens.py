"""Token de acceso de Polar: lo lee del almacén de secretos, lo renueva si está
por caducar y guarda el nuevo par. Es lo que usarán `polar-probe` y, después,
el conector de Polar y el planificador.

La documentación de la API v4 indica que el access token dura 12 h; en la primera
autorización real la hora de caducidad guardada sugiere una duración menor. Por eso
el margen de renovación es corto (5 min) y no depende de esa cifra: se renueva
siempre según el `expires_at` que Polar haya dado de verdad.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from .. import config
from . import polar_oauth

REFRESH_MARGIN = timedelta(minutes=5)


class TokenError(RuntimeError):
    """Falta alguna credencial o autorización; el mensaje dice qué hacer."""


def _parse_expiry(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def get_access_token(
    *,
    http: httpx.Client | None = None,
    secret_getter: Callable[[str], str | None] | None = None,
    secret_setter: Callable[[str, str], None] | None = None,
    now: datetime | None = None,
) -> str:
    # Se resuelven aquí y no como valores por defecto del parámetro, para que un
    # monkeypatch de `config.get_secret` se respete (mismo motivo que en runner.py).
    get = secret_getter or config.get_secret
    put = secret_setter or config.set_secret

    client_id = get("polar_client_id")
    client_secret = get("polar_client_secret")
    if not client_id or not client_secret:
        raise TokenError(
            "Faltan las credenciales del cliente de Polar: "
            "ares secret set polar_client_id / polar_client_secret"
        )

    access = get("polar_access_token")
    refresh_tok = get("polar_refresh_token")
    expiry_raw = get("polar_token_expiry")
    if not access or not refresh_tok or not expiry_raw:
        raise TokenError("Este equipo no está autorizado en Polar: ejecuta ares polar-auth")

    expires_at = _parse_expiry(expiry_raw)
    if (now or datetime.now(UTC)) + REFRESH_MARGIN < expires_at:
        return access

    tokens = polar_oauth.refresh(client_id, client_secret, refresh_tok, http)
    put("polar_access_token", tokens.access_token)
    put("polar_refresh_token", tokens.refresh_token)
    put("polar_token_expiry", tokens.expires_at.isoformat())
    return tokens.access_token
