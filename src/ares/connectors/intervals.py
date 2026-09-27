"""Conector de intervals.icu: bienestar diario (forma, fatiga, VFC, pulso, sueño...)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from .base import HttpClient, mark_status, store_raw

BASE_URL = "https://intervals.icu/api/v1"
SOURCE = "intervals"
ENDPOINT = "wellness"


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    inserted: int

    @property
    def unchanged(self) -> int:
        return self.fetched - self.inserted


def fetch_wellness(
    http: HttpClient, api_key: str, athlete_id: str, oldest: date, newest: date
) -> list[dict]:
    resp = http.get(
        f"{BASE_URL}/athlete/{athlete_id}/wellness",
        params={"oldest": oldest.isoformat(), "newest": newest.isoformat()},
        auth=("API_KEY", api_key),
        headers={"Accept": "application/json"},
    )
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("Respuesta inesperada de intervals.icu: se esperaba una lista de días")
    return data


def sync_wellness(
    conn: duckdb.DuckDBPyConnection,
    http: HttpClient,
    api_key: str,
    athlete_id: str,
    days: int,
    today: date | None = None,
) -> SyncResult:
    newest = today or date.today()
    oldest = newest - timedelta(days=days - 1)
    try:
        records = fetch_wellness(http, api_key, athlete_id, oldest, newest)
    except Exception as exc:
        mark_status(conn, source=SOURCE, endpoint=ENDPOINT, ok=False, error=str(exc))
        raise
    inserted = 0
    for rec in records:
        day = date.fromisoformat(str(rec["id"])[:10])  # intervals.icu usa la fecha como id
        if store_raw(conn, source=SOURCE, endpoint=ENDPOINT, day=day, body=rec):
            inserted += 1
    mark_status(conn, source=SOURCE, endpoint=ENDPOINT, ok=True)
    return SyncResult(fetched=len(records), inserted=inserted)
