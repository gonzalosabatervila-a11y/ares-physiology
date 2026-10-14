"""Conector de Tredict: lista de actividades por la Personal API.

Documentación oficial verificada el 27/09/2026:
https://www.tredict.com/blog/oauth_docs/ y https://www.tredict.com/skills/setup.md
Base: https://www.tredict.com/api/oauth/v2/ · Auth: `Authorization: Bearer <token>`.
`GET activityList?startDate&pageSize` devuelve, sin `startDate`, las más recientes primero;
pagina siguiendo `_links.next.href` hasta que falta (última página) o hasta una fecha límite.
Límite de la API: 10 peticiones/s en descarga (ver `PAGE_DELAY_S`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import re
import time
from collections.abc import Callable
from typing import Any

import duckdb

from .base import HttpClient, mark_status, store_raw

BASE_URL = "https://www.tredict.com/api/oauth/v2"
SOURCE = "tredict"
ENDPOINT = "activity"
DEFAULT_PAGE_SIZE = 200
PAGE_DELAY_S = 0.15  # holgura frente al límite de 10 req/s de descarga
DETAIL_ENDPOINT = "activity_detail"
MAX_DETAIL_DOWNLOADS = 30  # lote voluntario y acotado para evitar llamadas masivas
ACTIVITY_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{3,80}$")


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    inserted: int

    @property
    def unchanged(self) -> int:
        return self.fetched - self.inserted


def _activity_date(item: dict[str, Any]) -> date:
    return datetime.fromisoformat(item["date"].replace("Z", "+00:00")).date()


def fetch_page(
    http: HttpClient,
    token: str,
    *,
    start_date: datetime | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    params: dict[str, str | int] = {"pageSize": page_size}
    if start_date is not None:
        params["startDate"] = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    resp = http.get(
        f"{BASE_URL}/activityList",
        params=params,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json;charset=UTF-8"},
    )
    return resp.json()


def fetch_next(http: HttpClient, token: str, href: str) -> dict[str, Any]:
    resp = http.get(
        href,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json;charset=UTF-8"},
    )
    return resp.json()


def sync_activities(
    conn: duckdb.DuckDBPyConnection,
    http: HttpClient,
    token: str,
    days: int,
    today: date | None = None,
    sleep=lambda s: None,
) -> SyncResult:
    """Recorre la lista de actividades desde hoy hacia atrás, `days` días como máximo."""
    since = (today or date.today()) - timedelta(days=days - 1)
    fetched = inserted = 0
    try:
        page = fetch_page(http, token)
        while True:
            items = page.get("_embedded", {}).get("activityList", [])
            reached_limit = False
            for item in items:
                if _activity_date(item) < since:
                    reached_limit = True
                    break
                fetched += 1
                if store_raw(
                    conn, source=SOURCE, endpoint=ENDPOINT, day=_activity_date(item), body=item
                ):
                    inserted += 1
            next_href = page.get("_links", {}).get("next", {}).get("href")
            if reached_limit or not next_href or not items:
                break
            sleep(PAGE_DELAY_S)
            page = fetch_next(http, token, next_href)
    except Exception as exc:
        mark_status(conn, source=SOURCE, endpoint=ENDPOINT, ok=False, error=str(exc))
        raise
    mark_status(conn, source=SOURCE, endpoint=ENDPOINT, ok=True)
    return SyncResult(fetched=fetched, inserted=inserted)


# ------------------------------------------------------------------- entrenos en detalle


def fetch_activity_detail(http: HttpClient, token: str, activity_id: str) -> dict[str, Any]:
    """WHOOP no sustituye a los datos de entrenamiento: detalle, laps y series.

    Referencia: Tredict Personal API v2, GET /activity/{id}; parámetros
    extraValues=1, withLaps=1 y allSeries=1.
    """
    if not ACTIVITY_ID_RE.fullmatch(activity_id):
        raise ValueError("ID de actividad Tredict no válido")
    response = http.get(
        f"{BASE_URL}/activity/{activity_id}",
        params={"extraValues": "1", "withLaps": "1", "allSeries": "1"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json;charset=UTF-8"},
    )
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("summary"), dict):
        raise ValueError("Detalle Tredict sin summary válido")
    actual_id = body.get("_id") or body.get("id")
    if actual_id is not None and str(actual_id) != activity_id:
        raise ValueError("Respuesta Tredict de otra actividad")
    # Los sensores no siempre entregan laps o series: su ausencia es válida.
    return body


def sync_activity_details(
    conn: duckdb.DuckDBPyConnection,
    http: HttpClient,
    token: str,
    *,
    days: int = 30,
    limit: int = 10,
    today: date | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> SyncResult:
    """Carga manual de detalles seleccionados de la lista ya sincronizada.

    Nunca arranca desde el planificador. Se almacena el JSON bruto con su
    procedencia para analizarlo después. No sincroniza credenciales ni sube
    datos deportivos a GitHub.
    """
    if days < 1 or days > 365:
        raise ValueError("days debe estar entre 1 y 365")
    if limit < 1 or limit > MAX_DETAIL_DOWNLOADS:
        raise ValueError(f"limit debe estar entre 1 y {MAX_DETAIL_DOWNLOADS}")
    oldest = (today or date.today()) - timedelta(days=days - 1)
    rows = conn.execute(
        """SELECT day, body FROM raw_payload
           WHERE source='tredict' AND endpoint='activity'
           ORDER BY day DESC, fetched_at DESC LIMIT 1200"""
    ).fetchall()
    candidates: list[tuple[str, date]] = []
    seen: set[str] = set()
    for day, raw in rows:
        if day < oldest:
            break
        item = json.loads(raw) if isinstance(raw, str) else raw
        identifier = str(item.get("id", ""))
        if identifier in seen or not ACTIVITY_ID_RE.fullmatch(identifier):
            continue
        seen.add(identifier)
        candidates.append((identifier, day))
        if len(candidates) >= limit:
            break

    fetched = inserted = 0
    try:
        for i, (identifier, day) in enumerate(candidates):
            if i:
                sleep(0.2)  # <10 peticiones/s, límite Tredict
            detail = fetch_activity_detail(http, token, identifier)
            if store_raw(
                conn, source=SOURCE, endpoint=DETAIL_ENDPOINT, day=day, body=detail
            ):
                inserted += 1
            fetched += 1
    except Exception as exc:
        mark_status(conn, source=SOURCE, endpoint=DETAIL_ENDPOINT, ok=False, error=str(exc))
        raise
    mark_status(conn, source=SOURCE, endpoint=DETAIL_ENDPOINT, ok=True)
    return SyncResult(fetched=fetched, inserted=inserted)
