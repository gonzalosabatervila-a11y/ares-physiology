"""Lógica compartida de sincronización: la usan tanto `ares sync` (manual) como
el planificador interno de `ares serve`. Decide cuántos días pedir (incremental
o backfill de recuperación) y deja el registro en job_runs con la misma forma
en los dos casos, para que Lab no tenga que distinguir origen manual/automático.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import duckdb
import httpx
import structlog

from . import db, jobs
from .config import Settings, get_secret
from .connectors import whoop, whoop_tokens
from .connectors.base import HttpClient
from .connectors.intervals import SyncResult as IntervalsResult
from .connectors.intervals import sync_wellness
from .connectors.tredict import SyncResult as TredictResult
from .connectors.tredict import sync_activities
from .metrics import nightly

SyncOutcome = IntervalsResult | TredictResult | whoop.SyncResult

INCREMENTAL_DAYS = 3
SOURCE_SECRETS = {"intervals": "intervals_api_key", "tredict": "tredict_token"}
SOURCE_ENDPOINT = {
    "intervals": "wellness",
    "tredict": "activity",
    "whoop": "recovery",
}
SOURCES = ("intervals", "tredict", "whoop")  # WHOOP se autentica con OAuth, no con una clave
DAY_WHOOP_ENDPOINTS = ("cycle",)  # de día solo cambian los pasos y el strain del ciclo


class SyncSkipped(RuntimeError):
    """La sincronización no se intentó (falta clave o la base no está al día)."""


@dataclass(frozen=True)
class RunResult:
    source: str
    fetched: int
    inserted: int
    days_used: int
    backfill: bool
    nights: int | None = None  # noches reescritas en daily_metrics (WHOOP)
    history: bool = False  # carga histórica inicial (WHOOP_HISTORY_DAYS)


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
    whoop_endpoints: tuple[str, ...] = whoop.ALL_ENDPOINTS,
    token_http: httpx.Client | None = None,
) -> RunResult:
    # `secret_getter` se resuelve aquí, no como valor por defecto del parámetro:
    # así un monkeypatch de `get_secret` a nivel de módulo (tests, o un backend
    # de secretos distinto en el futuro) se respeta también en llamadas sin él.
    endpoint = SOURCE_ENDPOINT[source]
    history = False
    if source == "whoop":
        # Antes de pedir nada (también la carga histórica): secretos y token válido. Si no los
        # hay, se registra y se sigue con las demás fuentes.
        try:
            whoop_tokens.get_access_token(settings.data_dir, http=token_http)
        except whoop_tokens.TokenError as exc:
            if not whoop.has_raw(conn, settings.device_id):
                logger.warning("whoop_history_pending", reason=str(exc))
            raise SyncSkipped(str(exc)) from exc
        key = ""
        history = days is None and not whoop.has_raw(conn, settings.device_id)
    else:
        secret = (secret_getter or get_secret)(SOURCE_SECRETS[source])
        if not secret:
            raise SyncSkipped(f"Falta el secreto {SOURCE_SECRETS[source]}")
        key = secret

    used_days, was_backfill = (
        (days, False)
        if days is not None
        else (settings.whoop_history_days, True)
        if history
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
    nights: int | None = None
    try:
        res: SyncOutcome
        if source == "whoop":
            res, nights = _sync_whoop(
                conn,
                settings,
                http_client,
                used_days,
                whoop_endpoints,
                token_http,
                full_rebuild=was_backfill,
                logger=logger,
            )
        elif source == "intervals":
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

    detail: dict[str, object] = {
        "days": used_days,
        "fetched": res.fetched,
        "inserted": res.inserted,
        "backfill": was_backfill,
    }
    if nights is not None:
        detail["nights"] = nights
        detail["history"] = history
    jobs.finish(conn, run_id, "ok", detail)
    logger.info("sync_ok", source=source, endpoint=endpoint, **detail)
    return RunResult(
        source=source,
        fetched=res.fetched,
        inserted=res.inserted,
        days_used=used_days,
        backfill=was_backfill,
        nights=nights,
        history=history,
    )


def _sync_whoop(
    conn: duckdb.DuckDBPyConnection,
    settings: Settings,
    http_client: HttpClient,
    used_days: int,
    endpoints: tuple[str, ...],
    token_http: httpx.Client | None,
    *,
    full_rebuild: bool,
    logger: structlog.stdlib.BoundLogger,
) -> tuple[whoop.SyncResult, int]:
    """Bruto primero; después, noches recalculadas desde lo bruto (todas tras una carga
    histórica o un backfill; si no, las de la ventana pedida)."""
    tz = ZoneInfo(settings.tz)
    start, end = whoop.window(used_days)
    res = whoop.sync_whoop(
        conn,
        http_client,
        settings.data_dir,
        device_id=settings.device_id,
        tz=tz,
        start=start,
        end=end,
        endpoints=endpoints,
        token_http=token_http,
    )
    adapter = whoop.WhoopAdapter(tz)
    since = None if full_rebuild else (datetime.now(tz).date() - timedelta(days=used_days))
    nights = nightly.rebuild(
        conn, adapter, device_id=settings.device_id, algo_version=settings.algo_version, since=since
    )
    if any(adapter.invalid.values()):
        logger.warning("whoop_contract_invalid", fuente="whoop", **adapter.invalid)
    for reason in adapter.dropped:
        logger.warning("whoop_night_dropped", fuente="whoop", reason=reason)
    return res, nights


def run_all(
    conn: duckdb.DuckDBPyConnection,
    settings: Settings,
    logger: structlog.stdlib.BoundLogger,
    job: str = "manual",
) -> list[RunResult | SyncSkipped]:
    """Sincroniza todas las fuentes conocidas; una fuente fallida no bloquea las demás.
    De día (`job="day"`) WHOOP solo pide el ciclo."""
    out: list[RunResult | SyncSkipped] = []
    whoop_endpoints = DAY_WHOOP_ENDPOINTS if job == "day" else whoop.ALL_ENDPOINTS
    for source in SOURCES:
        try:
            out.append(
                run_source_sync(
                    conn, source, settings, logger=logger, whoop_endpoints=whoop_endpoints
                )
            )
        except SyncSkipped as exc:
            logger.warning("sync_skipped", source=source, reason=str(exc))
            out.append(exc)
        except Exception:  # ya registrado en job_runs/log dentro de run_source_sync
            continue
    return out


def ensure_ready(conn: duckdb.DuckDBPyConnection, settings: Settings) -> list[int]:
    """Aplica migraciones pendientes si las hay; devuelve las versiones aplicadas."""
    return db.migrate(conn, settings.migrations_dir)
