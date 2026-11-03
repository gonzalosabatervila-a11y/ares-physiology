"""Conector oficial WHOOP API v2: OAuth2 y sincronización bruta, sin inferir métricas.

Las cuatro colecciones se almacenan por registro (no por página) para mantener
versiones, hashes y trazabilidad ARES. Los tokens permanecen en el keyring local.
Referencia: https://developer.whoop.com/api/
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import duckdb
import httpx

from .. import config
from .base import HttpClient, mark_status, store_raw

API_ROOT = "https://api.prod.whoop.com/developer/v2"
AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
SCOPES = "offline read:cycles read:recovery read:sleep read:workout"
ENDPOINTS = {
    "cycle": "/cycle",
    "recovery": "/recovery",
    "sleep": "/activity/sleep",
    "workout": "/activity/workout",
}
REFRESH_MARGIN = timedelta(minutes=5)


class WhoopError(RuntimeError):
    """Error sin secretos ni respuesta HTTP sensible."""


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: datetime


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    inserted: int


def authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    if len(state) != 8:
        raise ValueError("WHOOP exige un state OAuth de ocho caracteres.")
    return AUTH_URL + "?" + urlencode({
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": SCOPES, "state": state,
    })


def new_state() -> str:
    return secrets.token_hex(4)


def _parse_tokens(body: dict[str, Any], fallback_refresh: str | None = None) -> TokenSet:
    access = body.get("access_token")
    refresh = body.get("refresh_token") or fallback_refresh
    if not access or not refresh:
        raise WhoopError("WHOOP no devolvió un par de tokens válido.")
    seconds = int(body["expires_in"])
    return TokenSet(access, refresh, datetime.now(UTC) + timedelta(seconds=seconds))


def _request_tokens(
    data: dict[str, str],
    *,
    http: httpx.Client | None = None,
    fallback_refresh: str | None = None,
) -> TokenSet:
    client = http or httpx.Client(timeout=30.0)
    try:
        response = client.post(
            TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        return _parse_tokens(response.json(), fallback_refresh=fallback_refresh)
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        # No imprimir el cuerpo HTTP ni códigos de autorización ni refresh tokens.
        raise WhoopError("No se pudo completar el intercambio OAuth con WHOOP.") from exc
    finally:
        if http is None:
            client.close()


def exchange_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str,
    *, http: httpx.Client | None = None,
) -> TokenSet:
    return _request_tokens({
        "grant_type": "authorization_code", "code": code,
        "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }, http=http)


def refresh_tokens(
    refresh_token: str, client_id: str, client_secret: str,
    *, http: httpx.Client | None = None,
) -> TokenSet:
    return _request_tokens({
        "grant_type": "refresh_token", "refresh_token": refresh_token,
        "client_id": client_id, "client_secret": client_secret, "scope": "offline",
    }, http=http, fallback_refresh=refresh_token)


def get_access_token(
    *, now: datetime | None = None, http: httpx.Client | None = None,
) -> str:
    get = config.get_secret
    client_id, secret = get("whoop_client_id"), get("whoop_client_secret")
    if not client_id or not secret:
        raise WhoopError("Configura whoop_client_id y whoop_client_secret en el keyring.")
    access, refresh = get("whoop_access_token"), get("whoop_refresh_token")
    expires = get("whoop_token_expiry")
    if not access or not refresh or not expires:
        raise WhoopError("WHOOP pendiente de autorizar: ejecuta ares whoop-auth.")
    expiry = datetime.fromisoformat(expires)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) + REFRESH_MARGIN < expiry:
        return access
    updated = refresh_tokens(refresh, client_id, secret, http=http)
    # WHOOP rota el refresh token; nunca ejecutar múltiples sincronizadores a la vez.
    config.set_secret("whoop_access_token", updated.access_token)
    config.set_secret("whoop_refresh_token", updated.refresh_token)
    config.set_secret("whoop_token_expiry", updated.expires_at.isoformat())
    return updated.access_token


def _local_day(record: dict[str, Any], endpoint: str, tz: ZoneInfo,
               sleep_dates: dict[str, date]) -> date:
    if endpoint == "recovery" and record.get("sleep_id") in sleep_dates:
        return sleep_dates[record["sleep_id"]]
    # El sueño y el entrenamiento se atribuyen a su fin, el ciclo a su inicio.
    key = "start" if endpoint == "cycle" else "end"
    timestamp = record.get(key) or record.get("created_at")
    if not timestamp:
        raise WhoopError(f"Registro WHOOP sin fecha ({endpoint}).")
    parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise WhoopError("WHOOP devolvió una fecha sin zona horaria.")
    return parsed.astimezone(tz).date()


def _fetch_records(
    client: HttpClient, endpoint: str, token: str, since: datetime,
) -> list[dict[str, Any]]:
    path = ENDPOINTS[endpoint]
    params: dict[str, Any] = {
        "start": since.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "limit": 25,
    }
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _ in range(200):
        response = client.get(
            API_ROOT + path, headers={"Authorization": f"Bearer {token}"}, params=params
        )
        body = response.json()
        records = body.get("records")
        if not isinstance(records, list):
            raise WhoopError(f"Respuesta de colección WHOOP inesperada ({endpoint}).")
        items.extend(records)
        cursor = body.get("next_token")
        if not cursor:
            return items
        if not isinstance(cursor, str) or cursor in seen:
            raise WhoopError(f"Paginación WHOOP inválida ({endpoint}).")
        seen.add(cursor)
        params["nextToken"] = cursor
    raise WhoopError(f"WHOOP superó el límite de páginas ({endpoint}).")


def sync_whoop(
    conn: duckdb.DuckDBPyConnection, http: HttpClient, token: str,
    days: int, tz_name: str = "Europe/Madrid", now: datetime | None = None,
) -> SyncResult:
    if not 1 <= days <= 730:
        raise ValueError("WHOOP: el periodo debe ser de 1 a 730 días.")
    tz = ZoneInfo(tz_name)
    since = (now or datetime.now(UTC)) - timedelta(days=days + 1)
    total, inserted = 0, 0
    sleep_dates: dict[str, date] = {}
    # Primero el sueño para asociar Recovery a la fecha real de despertar.
    for endpoint in ("sleep", "recovery", "cycle", "workout"):
        try:
            records = _fetch_records(http, endpoint, token, since)
            for item in records:
                if not isinstance(item, dict):
                    raise WhoopError(f"Registro WHOOP no válido ({endpoint}).")
                day = _local_day(item, endpoint, tz, sleep_dates)
                if endpoint == "sleep" and item.get("id"):
                    sleep_dates[str(item["id"])] = day
                if store_raw(conn, source="whoop", endpoint=endpoint, day=day, body=item):
                    inserted += 1
                total += 1
            mark_status(conn, source="whoop", endpoint=endpoint, ok=True)
        except Exception:
            mark_status(conn, source="whoop", endpoint=endpoint, ok=False,
                        error="Error de lectura o normalización WHOOP")
            raise
    return SyncResult(fetched=total, inserted=inserted)
