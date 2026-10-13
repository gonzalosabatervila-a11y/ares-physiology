"""De noches normalizadas a `daily_metrics` (Implementation Plan v0.3, §6).

- VFC: el rMSSD es del proveedor (MED · WHOOP); ARES solo aplica el logaritmo (CALC · ARES).
  Un valor ausente, ≤ 0 o fuera de la plausibilidad configurada invalida la noche: no hay
  épsilon silencioso.
- Calidad: high | fair | excluded, según lo que declara el proveedor y la plausibilidad.
- Pasos: el step_count del ciclo de WHOOP es segunda fuente; nunca se suma con Apple Salud.
- `rebuild` es idempotente: borra y vuelve a escribir el rango desde lo bruto, en una
  transacción. Ejecutarlo dos veces deja la base idéntica.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import duckdb

from ..provenance import WHOOP_HRV
from ..provider import NormalizedNight, PhysiologyProvider


@dataclass(frozen=True)
class QualityConfig:
    """Umbrales iniciales (Especificación v0.3, «Calidad del dato»); se calibran con datos."""

    rmssd_min: float = 5.0
    rmssd_max: float = 300.0
    high_min_sleep: int = 6 * 60
    fair_min_sleep: int = 4 * 60


DEFAULT_QUALITY = QualityConfig()


def compute_ln_rmssd(rmssd_ms: float | None, cfg: QualityConfig = DEFAULT_QUALITY) -> float | None:
    """ln del rMSSD del proveedor, o None si la muestra no es válida (sin épsilon)."""
    if rmssd_ms is None or not math.isfinite(rmssd_ms) or rmssd_ms <= 0:
        return None
    if not (cfg.rmssd_min <= rmssd_ms <= cfg.rmssd_max):
        return None
    return math.log(rmssd_ms)


def quality(night: NormalizedNight, cfg: QualityConfig = DEFAULT_QUALITY) -> str:
    """high: puntuada, sin calibración, sueño ≥ 6 h y rMSSD plausible.
    fair: puntuada, sin calibración, sueño de 4 a 6 h (y rMSSD plausible).
    excluded: lo demás (sin puntuar, no puntuable, calibración, siesta, sueño < 4 h,
    rMSSD ausente o implausible). Sin respaldo de otra fuente."""
    if not night.scored or night.calibrating is not False or night.is_nap:
        return "excluded"
    if night.sleep_min is None or night.sleep_min < cfg.fair_min_sleep:
        return "excluded"
    if compute_ln_rmssd(night.rmssd_ms, cfg) is None:
        return "excluded"
    return "high" if night.sleep_min >= cfg.high_min_sleep else "fair"


@dataclass(frozen=True)
class StepsCheck:
    """Comparación de pasos: cada fuente con su etiqueta; nunca un total sumado."""

    apple_day: int | None  # fuente oficial del día natural
    whoop_cycle: int | None  # segunda fuente: ciclo fisiológico, no día natural
    diff: int | None
    rel_diff: float | None


def steps_concordance(apple_day: int | None, whoop_cycle: int | None) -> StepsCheck:
    if apple_day is None or whoop_cycle is None:
        return StepsCheck(apple_day, whoop_cycle, None, None)
    diff = whoop_cycle - apple_day
    rel = diff / apple_day if apple_day else None
    return StepsCheck(apple_day, whoop_cycle, diff, rel)


COLUMNS = (
    "local_sleep_date",
    "device_id",
    "sleep_start",
    "sleep_end",
    "source_tz",
    "sleep_min",
    "rmssd_ms",
    "ln_rmssd",
    "hrv_tag",
    "hrv_origin",
    "rhr",
    "resp_rate",
    "spo2",
    "skin_temp",
    "provider_recovery",
    "steps_whoop_cycle",
    "score_state",
    "calibrating",
    "ctl",
    "atl",
    "quality",
    "algo_version",
    "adapter_version",
    "whoop_sleep_id",
    "whoop_cycle_id",
    "night_check",
)


def _load(conn: duckdb.DuckDBPyConnection) -> dict[date, tuple[float | None, float | None]]:
    """Forma y fatiga de intervals.icu por día (contexto de carga, no fisiología)."""
    rows = conn.execute(
        """SELECT day, try_cast(json_extract(body, '$.ctl') AS DOUBLE),
                  try_cast(json_extract(body, '$.atl') AS DOUBLE)
           FROM raw_intervals_wellness
           QUALIFY row_number() OVER (PARTITION BY day ORDER BY fetched_at DESC) = 1"""
    ).fetchall()
    return {d: (ctl, atl) for d, ctl, atl in rows}


def row_for(
    night: NormalizedNight,
    algo_version: str,
    load: tuple[float | None, float | None] = (None, None),
    cfg: QualityConfig = DEFAULT_QUALITY,
) -> tuple[object, ...]:
    ctl, atl = load
    return (
        night.local_sleep_date,
        night.device_id,
        night.sleep_start,
        night.sleep_end,
        night.source_tz,
        night.sleep_min,
        night.rmssd_ms,
        compute_ln_rmssd(night.rmssd_ms, cfg),
        WHOOP_HRV.tag,
        WHOOP_HRV.origin,
        night.rhr,
        night.resp_rate,
        night.spo2,
        night.skin_temp,
        night.provider_recovery,
        night.steps_provider_cycle,
        night.score_state,
        night.calibrating,
        ctl,
        atl,
        quality(night, cfg),
        algo_version,
        night.adapter_version,
        night.provider_sleep_id,
        night.provider_cycle_id,
        night.night_check,
    )


def rebuild(
    conn: duckdb.DuckDBPyConnection,
    provider: PhysiologyProvider,
    *,
    device_id: str,
    algo_version: str,
    since: date | None = None,
    cfg: QualityConfig = DEFAULT_QUALITY,
) -> int:
    """Recalcula `daily_metrics` del dispositivo desde la capa bruta: todo, o desde `since`.
    Devuelve cuántas noches quedan escritas en el rango."""
    nights = [
        n for n in provider.nights(conn, device_id) if since is None or n.local_sleep_date >= since
    ]
    dates = [n.local_sleep_date for n in nights]
    if len(dates) != len(set(dates)):
        raise ValueError(f"{provider.name}: más de una noche para el mismo día")
    load = _load(conn)
    rows = [
        row_for(n, algo_version, load.get(n.local_sleep_date, (None, None)), cfg) for n in nights
    ]
    placeholders = ", ".join("?" for _ in COLUMNS)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(
            "DELETE FROM daily_metrics "
            "WHERE device_id = ? AND (? IS NULL OR local_sleep_date >= ?)",
            [device_id, since, since],
        )
        if rows:
            conn.executemany(
                f"INSERT INTO daily_metrics ({', '.join(COLUMNS)}) VALUES ({placeholders})", rows
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)
