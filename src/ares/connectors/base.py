"""Base común de conectores: HTTP con reintentos y escritura en la capa bruta (solo añadir)."""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import duckdb
import httpx

RETRY_DELAYS = (2.0, 8.0, 30.0)
MAX_RETRY_AFTER = 900.0  # 429: como mucho, esperar a la siguiente ventana de 15 min


class ConnectorError(RuntimeError):
    pass


class HttpClient:
    """httpx con la política del plan: 3 reintentos (2, 8, 30 s + aleatoriedad).

    Reintenta 5xx, errores de red y 429 (respetando Retry-After). El resto de 4xx no.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = lambda: random.uniform(0, 1),
    ) -> None:
        self.client = client or httpx.Client(timeout=30.0)
        self.sleep = sleep
        self.jitter = jitter

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                resp = self.client.get(url, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
            else:
                if resp.status_code == 429 and attempt < len(RETRY_DELAYS):
                    wait = min(
                        float(resp.headers.get("Retry-After", RETRY_DELAYS[attempt])),
                        MAX_RETRY_AFTER,
                    )
                    self.sleep(wait)
                    continue
                if resp.status_code >= 500 and attempt < len(RETRY_DELAYS):
                    last_exc = ConnectorError(f"HTTP {resp.status_code} en {url}")
                elif resp.status_code >= 400:
                    raise ConnectorError(f"HTTP {resp.status_code} en {url}")
                else:
                    return resp
            if attempt < len(RETRY_DELAYS):
                self.sleep(RETRY_DELAYS[attempt] + self.jitter())
        raise ConnectorError(f"Sin respuesta válida tras reintentos: {url}") from last_exc


def canonical_sha256(body: Any) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def store_raw(
    conn: duckdb.DuckDBPyConnection,
    *,
    source: str,
    endpoint: str,
    day: date,
    body: Any,
    device_id: str | None = None,
) -> bool:
    """Añade a raw_payload si ese contenido no existe ya. Devuelve True si insertó."""
    sha = canonical_sha256(body)
    before = conn.execute(
        "SELECT count(*) FROM raw_payload WHERE source=? AND endpoint=? AND day=? AND sha256=?",
        [source, endpoint, day, sha],
    ).fetchone()
    if before and before[0]:
        return False
    conn.execute(
        "INSERT INTO raw_payload VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            source,
            endpoint,
            day,
            device_id,
            datetime.now(UTC),
            sha,
            json.dumps(body, ensure_ascii=False),
        ],
    )
    return True


def mark_status(
    conn: duckdb.DuckDBPyConnection,
    *,
    source: str,
    endpoint: str,
    ok: bool,
    error: str | None = None,
    device_id: str = "global",
) -> None:
    now = datetime.now(UTC)
    if ok:
        conn.execute(
            """INSERT INTO source_status (source, endpoint, device_id, last_ok)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (source, endpoint, device_id)
               DO UPDATE SET last_ok = excluded.last_ok""",
            [source, endpoint, device_id, now],
        )
    else:
        conn.execute(
            """INSERT INTO source_status (source, endpoint, device_id, last_error, error)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (source, endpoint, device_id)
               DO UPDATE SET last_error = excluded.last_error, error = excluded.error""",
            [source, endpoint, device_id, now, (error or "")[:500]],
        )
