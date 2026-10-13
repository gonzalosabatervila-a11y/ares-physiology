"""Conector WHOOP API v2 y adaptador Physiology Provider.

Descarga (sondeo, sin webhooks): recuperación, sueño, ciclo y entreno, con `start`/`end`,
`limit=25` y paginación (`nextToken` en la petición, `next_token` en la respuesta). Cada
registro se guarda tal cual en `raw_payload` antes de procesarlo, uno por fila (fe de erratas
v0.3): `day` es la fecha en ARES_TZ de su `start` (Recovery no tiene `start`: su `created_at`).

Adaptador: la noche es el sueño al que apunta `recovery.sleep_id`; se marca si es siesta, si no
es el no siesta más largo de su ciclo o si su `timezone_offset` no cuadra con ARES_TZ. La fecha
sale siempre de `sleep.end` en ARES_TZ. Los entrenos solo se guardan como contexto.

Modelos según el OpenAPI oficial (api.prod.whoop.com/developer/doc/openapi.json, 02/10/2026).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import duckdb
import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from ..provider import SCORED, NormalizedNight
from ..timeutil import local_sleep_date, to_utc
from . import whoop_tokens
from .base import ConnectorError, HttpClient, mark_status, store_raw

BASE_URL = "https://api.prod.whoop.com/developer"
SOURCE = "whoop"
PATHS = {
    "recovery": "/v2/recovery",
    "sleep": "/v2/activity/sleep",
    "cycle": "/v2/cycle",
    "workout": "/v2/activity/workout",
}
ALL_ENDPOINTS = ("recovery", "sleep", "cycle", "workout")
PAGE_LIMIT = 25  # máximo de la API
MAX_PAGES = 400  # tope de seguridad ante un next_token que no termine
ADAPTER_VERSION = "whoop-adapter-1.0"
MODEL_NAME = "WHOOP"

ScoreState = Literal["SCORED", "PENDING_SCORE", "UNSCORABLE"]


# ---------------------------------------------------------------- modelos (contrato API v2)


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class RecoveryScore(_Model):
    user_calibrating: bool
    recovery_score: float
    resting_heart_rate: float
    hrv_rmssd_milli: float
    spo2_percentage: float | None = None
    skin_temp_celsius: float | None = None


class Recovery(_Model):
    cycle_id: int
    sleep_id: str
    user_id: int
    created_at: datetime
    updated_at: datetime
    score_state: ScoreState
    score: RecoveryScore | None = None


class StageSummary(_Model):
    total_in_bed_time_milli: int
    total_awake_time_milli: int
    total_no_data_time_milli: int
    total_light_sleep_time_milli: int
    total_slow_wave_sleep_time_milli: int
    total_rem_sleep_time_milli: int
    sleep_cycle_count: int
    disturbance_count: int


class SleepScore(_Model):
    stage_summary: StageSummary
    sleep_needed: dict[str, Any]
    respiratory_rate: float | None = None
    sleep_performance_percentage: float | None = None
    sleep_consistency_percentage: float | None = None
    sleep_efficiency_percentage: float | None = None


class Sleep(_Model):
    id: str
    cycle_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    start: datetime
    end: datetime
    timezone_offset: str
    nap: bool
    score_state: ScoreState
    score: SleepScore | None = None


class CycleScore(_Model):
    strain: float
    kilojoule: float
    average_heart_rate: int
    max_heart_rate: int


class Cycle(_Model):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    start: datetime
    end: datetime | None = None  # ciclo en curso: sin fin
    timezone_offset: str
    score_state: ScoreState
    score: CycleScore | None = None
    step_count: int | None = None  # puede ser nulo (pulsera no llevada todo el ciclo)


class Workout(_Model):
    id: str
    user_id: int
    created_at: datetime
    updated_at: datetime
    start: datetime
    end: datetime
    timezone_offset: str
    sport_name: str
    score_state: ScoreState


MODELS: dict[str, type[_Model]] = {
    "recovery": Recovery,
    "sleep": Sleep,
    "cycle": Cycle,
    "workout": Workout,
}


# ---------------------------------------------------------------------------- descarga


def _iso(dt: datetime) -> str:
    return to_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def raw_day(endpoint: str, record: dict[str, Any], tz: ZoneInfo) -> date:
    key = "created_at" if endpoint == "recovery" else "start"
    return to_utc(_parse_ts(str(record[key]))).astimezone(tz).date()


def fetch_collection(
    http: HttpClient,
    endpoint: str,
    start: datetime,
    end: datetime,
    authorized: Callable[[Callable[[str], httpx.Response]], httpx.Response],
) -> list[dict[str, Any]]:
    """Todas las páginas de una colección. `authorized(send)` pone el token (y renueva una vez
    ante 401); `send(token)` hace la petición."""
    url = BASE_URL + PATHS[endpoint]
    base_params = {"limit": str(PAGE_LIMIT), "start": _iso(start), "end": _iso(end)}
    records: list[dict[str, Any]] = []
    next_token: str | None = None
    for _ in range(MAX_PAGES):
        params = dict(base_params)
        if next_token:
            params["nextToken"] = next_token

        def send(token: str, params: dict[str, str] = params) -> httpx.Response:
            return http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                passthrough=frozenset({401}),
            )

        body = authorized(send).json()
        page = body.get("records") if isinstance(body, dict) else None
        if not isinstance(page, list):
            raise ConnectorError(f"Respuesta inesperada de WHOOP en {endpoint}: sin 'records'")
        records.extend(page)
        next_token = body.get("next_token") or None
        if not next_token:
            return records
    raise ConnectorError(f"WHOOP {endpoint}: más de {MAX_PAGES} páginas; se corta por seguridad")


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    inserted: int
    by_endpoint: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def unchanged(self) -> int:
        return self.fetched - self.inserted


def register_device(conn: duckdb.DuckDBPyConnection, device_id: str, days: Iterable[date]) -> None:
    days = list(days)
    if not days:
        return
    conn.execute(
        """INSERT INTO devices (device_id, model, first_day, last_day, provider)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (device_id) DO UPDATE SET
             first_day = least(devices.first_day, excluded.first_day),
             last_day = greatest(devices.last_day, excluded.last_day),
             provider = excluded.provider,
             model = excluded.model""",
        [device_id, MODEL_NAME, min(days), max(days), SOURCE],
    )


def sync_whoop(
    conn: duckdb.DuckDBPyConnection,
    http: HttpClient,
    data_dir: Path,
    *,
    device_id: str,
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
    endpoints: Iterable[str] = ALL_ENDPOINTS,
    token_http: httpx.Client | None = None,
) -> SyncResult:
    """Descarga y guarda en bruto. Un endpoint fallido se marca en source_status y corta la
    ejecución (lo ya guardado se queda: la capa bruta solo añade)."""

    def authorized(send: Callable[[str], httpx.Response]) -> httpx.Response:
        return whoop_tokens.call_with_token(send, data_dir, http=token_http)

    fetched = inserted = 0
    by_endpoint: dict[str, tuple[int, int]] = {}
    days: list[date] = []
    for endpoint in endpoints:
        try:
            records = fetch_collection(http, endpoint, start, end, authorized)
        except Exception as exc:
            mark_status(
                conn,
                source=SOURCE,
                endpoint=endpoint,
                ok=False,
                error=str(exc),
                device_id=device_id,
            )
            raise
        new = 0
        for rec in records:
            day = raw_day(endpoint, rec, tz)
            days.append(day)
            if store_raw(
                conn, source=SOURCE, endpoint=endpoint, day=day, body=rec, device_id=device_id
            ):
                new += 1
        mark_status(conn, source=SOURCE, endpoint=endpoint, ok=True, device_id=device_id)
        by_endpoint[endpoint] = (len(records), new)
        fetched += len(records)
        inserted += new
    register_device(conn, device_id, days)
    return SyncResult(fetched=fetched, inserted=inserted, by_endpoint=by_endpoint)


def has_raw(conn: duckdb.DuckDBPyConnection, device_id: str) -> bool:
    row = conn.execute(
        "SELECT count(*) FROM raw_payload WHERE source = ? AND device_id = ?",
        [SOURCE, device_id],
    ).fetchone()
    return bool(row and row[0])


# ------------------------------------------------------------------------- adaptador


def _offset(raw: str) -> timedelta | None:
    """Time Zone Designator de WHOOP: '+hh:mm', '-hh:mm' o 'Z'."""
    if raw == "Z":
        return timedelta(0)
    try:
        sign = -1 if raw[0] == "-" else 1
        hh, mm = raw[1:].split(":")
        return sign * timedelta(hours=int(hh), minutes=int(mm))
    except (ValueError, IndexError):
        return None


def offset_matches(sleep: Sleep, tz: ZoneInfo) -> bool:
    """El offset de WHOOP cuadra si coincide con el de ARES_TZ al empezar o al terminar el
    sueño (la noche del cambio de hora tiene los dos)."""
    off = _offset(sleep.timezone_offset)
    if off is None:
        return False
    return off in {
        to_utc(sleep.start).astimezone(tz).utcoffset(),
        to_utc(sleep.end).astimezone(tz).utcoffset(),
    }


def _latest(
    conn: duckdb.DuckDBPyConnection, endpoint: str, device_id: str, key: str
) -> tuple[dict[Any, Any], int]:
    """Última versión válida de cada registro (por `updated_at`). Devuelve también cuántos
    cuerpos no cumplen el contrato, que se ignoran (y se registran fuera)."""
    model = MODELS[endpoint]
    rows = conn.execute(
        f"SELECT body FROM raw_whoop_{endpoint} WHERE device_id = ? ORDER BY fetched_at",
        [device_id],
    ).fetchall()
    best: dict[Any, Any] = {}
    invalid = 0
    for (body,) in rows:
        try:
            obj = model.model_validate(json.loads(body) if isinstance(body, str) else body)
        except ValidationError:
            invalid += 1
            continue
        k = getattr(obj, key)
        cur = best.get(k)
        if cur is None or obj.updated_at >= cur.updated_at:  # type: ignore[attr-defined]
            best[k] = obj
    return best, invalid


def sleep_minutes(sleep: Sleep) -> int | None:
    if sleep.score is None:
        return None
    s = sleep.score.stage_summary
    total = (
        s.total_light_sleep_time_milli
        + s.total_slow_wave_sleep_time_milli
        + s.total_rem_sleep_time_milli
    )
    return round(total / 60_000)


def _worst(*states: str) -> str:
    order = ("UNSCORABLE", "PENDING_SCORE", SCORED)
    return min(states, key=order.index)


def _duration(s: Sleep) -> timedelta:
    return s.end - s.start


@dataclass
class WhoopAdapter:
    """Adaptador Physiology Provider de WHOOP sobre la capa bruta."""

    tz: ZoneInfo
    name: str = SOURCE
    adapter_version: str = ADAPTER_VERSION
    invalid: dict[str, int] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)

    def nights(self, conn: duckdb.DuckDBPyConnection, device_id: str) -> list[NormalizedNight]:
        recoveries, self.invalid["recovery"] = _latest(conn, "recovery", device_id, "cycle_id")
        sleeps, self.invalid["sleep"] = _latest(conn, "sleep", device_id, "id")
        cycles, self.invalid["cycle"] = _latest(conn, "cycle", device_id, "id")
        self.dropped = []

        by_cycle: dict[int, list[Sleep]] = {}
        for s in sleeps.values():
            by_cycle.setdefault(s.cycle_id, []).append(s)

        out: dict[date, NormalizedNight] = {}
        for rec in recoveries.values():
            sleep = sleeps.get(rec.sleep_id)
            if sleep is None:
                self.dropped.append(f"recuperación del ciclo {rec.cycle_id} sin su sueño")
                continue
            night = self._night(rec, sleep, by_cycle.get(rec.cycle_id, []), cycles, device_id)
            prev = out.get(night.local_sleep_date)
            if prev is not None:
                # Dos recuperaciones el mismo día local: se queda la de la noche no siesta más
                # larga (y si empatan, la que termina más tarde); la otra se registra.
                keep = max(
                    (prev, night),
                    key=lambda n: (not n.is_nap, n.sleep_end - n.sleep_start, n.sleep_end),
                )
                lost = night if keep is prev else prev
                self.dropped.append(
                    f"{lost.local_sleep_date}: dos noches el mismo día; descartado el sueño "
                    f"{lost.provider_sleep_id}"
                )
                night = keep
            out[night.local_sleep_date] = night
        return [out[d] for d in sorted(out)]

    def _night(
        self,
        rec: Recovery,
        sleep: Sleep,
        cycle_sleeps: list[Sleep],
        cycles: dict[Any, Any],
        device_id: str,
    ) -> NormalizedNight:
        checks: list[str] = []
        if sleep.nap:
            checks.append("siesta")
        candidates = [s for s in cycle_sleeps if not s.nap]
        if candidates:
            longest = max(candidates, key=lambda s: (_duration(s), s.end))
            if longest.id != sleep.id and not sleep.nap:
                checks.append("difiere_del_mas_largo")
        if not offset_matches(sleep, self.tz):
            checks.append("offset_incoherente")

        score = rec.score if rec.score_state == SCORED else None
        sleep_score = sleep.score if sleep.score_state == SCORED else None
        cycle = cycles.get(rec.cycle_id)
        end_utc = to_utc(sleep.end)
        return NormalizedNight(
            local_sleep_date=local_sleep_date(end_utc, self.tz),
            sleep_start=to_utc(sleep.start),
            sleep_end=end_utc,
            source_tz=sleep.timezone_offset,
            sleep_min=sleep_minutes(sleep) if sleep_score else None,
            rmssd_ms=score.hrv_rmssd_milli if score else None,
            rhr=score.resting_heart_rate if score else None,
            resp_rate=sleep_score.respiratory_rate if sleep_score else None,
            spo2=score.spo2_percentage if score else None,
            skin_temp=score.skin_temp_celsius if score else None,
            provider_recovery=score.recovery_score if score else None,
            score_state=_worst(rec.score_state, sleep.score_state),
            calibrating=score.user_calibrating if score else None,
            device_id=device_id,
            adapter_version=self.adapter_version,
            steps_provider_cycle=cycle.step_count if cycle else None,
            provider_sleep_id=sleep.id,
            provider_cycle_id=rec.cycle_id,
            night_check=",".join(checks) or "ok",
            is_nap=sleep.nap,
        )


def window(days: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[ahora − días, ahora] en UTC. `end` es exclusivo en la API y por defecto «ahora»."""
    end = now or datetime.now(UTC)
    return end - timedelta(days=days), end
