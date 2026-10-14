"""Temporal context: a workout and the WHOOP nights strictly before/after it.

Never match by calendar day alone: a 05:40 workout can overlap the end of
sleep, making same-date comparisons misleading. Uses UTC instants and
sleep_start/sleep_end from WHOOP; no inferred causal effects.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb


def _instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _night(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    day, start, end, sleep, hrv, rhr, recovery = row
    return {
        "date": day.isoformat(),
        "sleep_start": start.isoformat(),
        "sleep_end": end.isoformat(),
        "sleep_min": sleep,
        "rmssd_ms": hrv,
        "rhr": rhr,
        "recovery_whoop": recovery,
    }


def training_night_context(
    conn: duckdb.DuckDBPyConnection, device_id: str,
    activity_start_utc: str, duration_s: Any,
) -> dict[str, Any]:
    start = _instant(activity_start_utc)
    if start is None or not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool):
        return {"available": False, "reason": "Hora UTC o duración de la sesión ausente."}
    duration = float(duration_s)
    if not math.isfinite(duration) or not 0 < duration < 172800:
        return {"available": False, "reason": "Duración no válida para relación temporal."}
    end = start + timedelta(seconds=duration)

    common = (
        "FROM daily_metrics WHERE device_id = ? "
        "AND quality IN ('high', 'fair') "
        "AND score_state = 'SCORED' AND calibrating = false "
        "AND coalesce(night_check, 'ok') = 'ok' "
        "AND sleep_start IS NOT NULL AND sleep_end IS NOT NULL "
    )
    cols = "SELECT local_sleep_date, sleep_start, sleep_end, sleep_min, rmssd_ms, rhr, provider_recovery "
    previous = conn.execute(
        cols + common +
        "AND sleep_end <= ? AND sleep_end >= ? ORDER BY sleep_end DESC LIMIT 1",
        [device_id, start, start - timedelta(hours=72)],
    ).fetchone()
    following = conn.execute(
        cols + common +
        "AND sleep_start >= ? AND sleep_start <= ? ORDER BY sleep_start ASC LIMIT 1",
        [device_id, end, end + timedelta(hours=72)],
    ).fetchone()
    before = _night(previous)
    after = _night(following)
    delta = {}
    for name in ("rmssd_ms", "rhr", "sleep_min", "recovery_whoop"):
        a, b = before.get(name) if before else None, after.get(name) if after else None
        delta[name] = round(float(b) - float(a), 2) if a is not None and b is not None else None
    return {
        "available": before is not None or after is not None,
        "activity_start": start.isoformat(),
        "activity_end": end.isoformat(),
        "before": before,
        "after": after,
        "difference": delta,
        "method": (
            "Última noche válida que terminó antes del inicio; primera noche "
            "que comienza después del final del entrenamiento (ventana ±72 h). "
            "No demuestra causalidad: el cambio entre noches no acredita que lo haya provocado el entrenamiento."
        ),
    }
