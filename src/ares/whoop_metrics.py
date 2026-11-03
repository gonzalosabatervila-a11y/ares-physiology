"""Resumen exclusivamente descriptivo de datos WHOOP ya sincronizados en ARES.

No recalcula ni presenta Recovery de WHOOP como si fuera una decisión ARES.
Solo lectura; no expone tokens, IDs de usuario ni datos brutos.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import duckdb


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _hours_milli(value: Any) -> float | None:
    v = _number(value)
    return round(v / 3_600_000, 2) if v is not None else None


def _load(body: Any) -> dict[str, Any]:
    return json.loads(body) if isinstance(body, str) else dict(body)


def _latest_by_day(conn: duckdb.DuckDBPyConnection, limit: int) -> dict[str, dict[date, dict]]:
    # Conservamos payloads de eventos distintos y revisiones; preferimos el
    # último válido de cada día y categoría. Naps no sustituyen al sueño principal.
    rows = conn.execute(
        """SELECT endpoint, day, body FROM raw_payload
           WHERE source='whoop' AND endpoint IN ('recovery', 'cycle', 'sleep')
           ORDER BY fetched_at DESC, rowid DESC LIMIT ?""",
        [max(400, limit * 16)],
    ).fetchall()
    out: dict[str, dict[date, dict]] = {"recovery": {}, "cycle": {}, "sleep": {}}
    for endpoint, day, body in rows:
        record = _load(body)
        if endpoint == "sleep" and record.get("nap") is True:
            continue
        if day not in out[endpoint]:
            out[endpoint][day] = record
    return out


def summary(conn: duckdb.DuckDBPyConnection, days: int = 30) -> dict:
    if not 1 <= days <= 90:
        raise ValueError("days debe estar entre 1 y 90")
    latest = _latest_by_day(conn, days)
    all_days = sorted(set().union(*(set(m) for m in latest.values())), reverse=True)[:days]
    items = []
    for day in all_days:
        recovery = latest["recovery"].get(day, {})
        rec = recovery.get("score") or {} if recovery.get("score_state") == "SCORED" else {}
        cycle = latest["cycle"].get(day, {})
        cyc = cycle.get("score") or {} if cycle.get("score_state") == "SCORED" else {}
        sleep = latest["sleep"].get(day, {})
        sl = sleep.get("score") or {} if sleep.get("score_state") == "SCORED" else {}
        stage = sl.get("stage_summary") or {}
        need = sl.get("sleep_needed") or {}
        total_sleep = [
            _number(stage.get(key)) for key in (
                "total_light_sleep_time_milli",
                "total_slow_wave_sleep_time_milli",
                "total_rem_sleep_time_milli",
            )
        ]
        needed = [
            _number(need.get(key)) for key in (
                "baseline_milli", "need_from_sleep_debt_milli",
                "need_from_recent_strain_milli", "need_from_recent_nap_milli",
            )
        ]
        items.append({
            "date": day.isoformat(),
            "recovery": _number(rec.get("recovery_score")),
            "hrv_rmssd_ms": _number(rec.get("hrv_rmssd_milli")),
            "resting_hr": _number(rec.get("resting_heart_rate")),
            "spo2_pct": _number(rec.get("spo2_percentage")),
            "skin_temp_c": _number(rec.get("skin_temp_celsius")),
            "strain": _number(cyc.get("strain")),
            "steps": cycle.get("step_count"),
            "sleep_hours": _hours_milli(sum(total_sleep)) if all(
                x is not None for x in total_sleep
            ) else None,
            "sleep_need_hours": _hours_milli(sum(x or 0 for x in needed))
                if needed[0] is not None else None,
            "sleep_performance": _number(sl.get("sleep_performance_percentage")),
            "sleep_consistency": _number(sl.get("sleep_consistency_percentage")),
            "resp_rate": _number(sl.get("respiratory_rate")),
        })
    state = conn.execute(
        "SELECT MAX(last_ok) FROM source_status WHERE source='whoop'"
    ).fetchone()[0]
    return {
        "connected": bool(state),
        "last_sync": state.isoformat() if state else None,
        "source": "WHOOP API v2",
        "mode": "datos medidos / calculados por WHOOP; no son decisiones ARES",
        "records": items,
    }
