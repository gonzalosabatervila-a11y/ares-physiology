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
from typing import Any

import duckdb

from .base import HttpClient, mark_status, store_raw

BASE_URL = "https://www.tredict.com/api/oauth/v2"
SOURCE = "tredict"
ENDPOINT = "activity"
DEFAULT_PAGE_SIZE = 200
PAGE_DELAY_S = 0.15  # holgura frente al límite de 10 req/s de descarga


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
