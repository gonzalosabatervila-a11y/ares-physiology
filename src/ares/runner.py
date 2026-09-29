"""Lógica compartida de sincronización: la usan tanto `ares sync` (manual) como
el planificador interno de `ares serve`. Decide cuántos días pedir (incremental
o backfill de recuperación) y deja el registro en job_runs con la misma forma
en los dos casos, para que Lab no tenga que distinguir origen manual/automático.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import duckdb
import structlog

from . import db, jobs
from .config import Settings, get_secret
from .connectors.base import HttpClient
from .connectors.intervals import SyncResult as IntervalsResult
from .connectors.intervals import sync_wellness
from .connectors.tredict import SyncResult as TredictResult
from .connectors.tredict import sync_activities

SyncOutcome = IntervalsResult | TredictResult

INCREMENTAL_DAYS = 3
SOURCE_SECRETS = {"intervals": "intervals_api_key", "tredict": "tredict_token"}
SOURCE_ENDPOINT = {"intervals": "wellness", "tredict": "activity"}


class SyncSkipped(RuntimeError):
    """La sincronización no se intentó (falta clave o la base no está al día)."""


@dataclass(frozen=True)
class RunResult:
    source: str
    fetched: int
    inserted: int
    days_used: int
    backfill: bool


def days_to_request(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    endpoint: str,
    *,
    incremental: int,
    backfill_max: int,
    now: datetime | None = None,
) -> tuple[int, bool]:
    """Incremental salvo que no haya `last_ok` reciente (arranque tras ausencia,
    Implementation Plan §7/§8): entonces se pide `backfill_max` días una vez."""
    row = conn.execute(
        "SELECT last_ok FROM source_status WHERE source=? AND endpoint=?",
        [source, endpoint],
    ).fetchone()
    last_ok = row[0] if row else None
    if last_ok is None:
        return backfill_max, True
    cutoff = (now or datetime.now(UTC)) - timedelta(days=incremental)
    if last_ok < cutoff:
        return backfill_max, True
    return incremental, False


def run_source_sync(
    conn: duckdb.DuckDBPyConnection,
    source: str,
    settings: Settings,
    *,
    logger: structlog.stdlib.BoundLogger,
    secret_getter: Callable[[str], str | None] | None = None,
    http: HttpClient | None = None,
    days: int | None = None,
) -> RunResult:
    # `secret_getter` se resuelve aquí, no como valor por defecto del parámetro:
    # así un monkeypatch de `get_secret` a nivel de módulo (tests, o un backend
    # de secretos distinto en el futuro) se respeta también en llamadas sin él.
    endpoint = SOURCE_ENDPOINT[source]
    key = (secret_getter or get_secret)(SOURCE_SECRETS[source])
    if not key:
        raise SyncSkipped(f"Falta el secreto {SOURCE_SECRETS[source]}")

    used_days, was_backfill = (
        (days, False)
        if days is not None
        else days_to_request(
            conn,
            source,
            endpoint,
            incremental=INCREMENTAL_DAYS,
            backfill_max=settings.backfill_max_days,
        )
    )

    run_id = jobs.start(conn, f"sync_{source}", settings.rules_version)
    http_client = http or HttpClient()
    try:
        res: SyncOutcome
        if source == "intervals":
            res = sync_wellness(conn, http_client, key, settings.intervals_athlete_id, used_days)
        else:
            res = sync_activities(conn, http_client, key, used_days)
    except Exception as exc:
        jobs.finish(conn, run_id, "error", {"error": str(exc), "days": used_days})
        logger.error(
            "sync_failed",
            source=source,
            endpoint=endpoint,
            error=str(exc),
            days=used_days,
            backfill=was_backfill,
        )
        raise

    detail = {
        "days": used_days,
        "fetched": res.fetched,
        "inserted": res.inserted,
        "backfill": was_backfill,
    }
    jobs.finish(conn, run_id, "ok", detail)
    logger.info("sync_ok", source=source, endpoint=endpoint, **detail)
    return RunResult(
        source=source,
        fetched=res.fetched,
        inserted=res.inserted,
        days_used=used_days,
        backfill=was_backfill,
    )


def run_all(
    conn: duckdb.DuckDBPyConnection, settings: Settings, logger: structlog.stdlib.BoundLogger
) -> list[RunResult | SyncSkipped]:
    """Sincroniza todas las fuentes conocidas; una fuente fallida no bloquea las demás."""
    out: list[RunResult | SyncSkipped] = []
    for source in SOURCE_SECRETS:
        try:
            out.append(run_source_sync(conn, source, settings, logger=logger))
        except SyncSkipped as exc:
            logger.warning("sync_skipped", source=source, reason=str(exc))
            out.append(exc)
        except Exception:  # ya registrado en job_runs/log dentro de run_source_sync
            continue
    return out


def ensure_ready(conn: duckdb.DuckDBPyConnection, settings: Settings) -> list[int]:
    """Aplica migraciones pendientes si las hay; devuelve las versiones aplicadas."""
    return db.migrate(conn, settings.migrations_dir)
