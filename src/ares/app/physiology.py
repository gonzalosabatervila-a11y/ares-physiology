"""ARES Fisiología: perfil longitudinal WHOOP sin puntuaciones ni diagnósticos propios.

Separa cuatro conceptos:
- MED: lecturas del dispositivo, con calidad y fecha.
- CALC: estadísticos transparentes calculados por ARES.
- MODELO: recovery calculado por WHOOP, no por ARES.
- NO DISPONIBLE: los valores que el proveedor no entrega o invalida.

Solo lectura sobre daily_metrics. Sin ML, clasificación clínica ni extrapolaciones.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean
from typing import Any

import duckdb

METRICS: tuple[tuple[str, str, str, str, str], ...] = (
    ("hrv", "Variabilidad cardíaca", "rmssd_ms", "ms", "MED · WHOOP"),
    ("rhr", "Pulso en reposo", "rhr", "lpm", "MED · WHOOP"),
    ("sleep", "Sueño efectivo", "sleep_min", "min", "MED · WHOOP"),
    ("resp", "Frecuencia respiratoria", "resp_rate", "rpm", "MED · WHOOP"),
    ("spo2", "Saturación nocturna", "spo2", "%", "MED · WHOOP"),
    ("temp", "Temperatura cutánea", "skin_temp", "°C", "MED · WHOOP"),
    ("recovery", "Recovery WHOOP", "provider_recovery", "%", "MODELO · WHOOP"),
)

VALID_QUALITY = {"high", "fair"}
MAX_DAYS = 365


def _number(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        value = float(x)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _usable(row: dict[str, Any]) -> bool:
    # No eliminar los datos inválidos de la serie: se hacen explícitos como huecos.
    # Una incoherencia de huso horario o selección de siesta es una razón adicional
    # para no utilizar esa noche en la referencia fisiológica.
    return (
        row["quality"] in VALID_QUALITY
        and row["score_state"] == "SCORED"
        and row["calibrating"] is False
        and row["night_check"] == "ok"
    )


def _metric(
    rows: list[dict[str, Any]], key: str, column: str, label: str, unit: str, origin: str
) -> dict[str, Any]:
    last_day = rows[-1]["date"] if rows else None
    series = [
        {"date": r["date"].isoformat(), "v": _number(r[column]) if _usable(r) else None}
        for r in rows
    ]
    if last_day is None:
        return {
            "key": key, "label": label, "unit": unit, "origin": origin, "latest": None,
            "mean7": None, "mean28": None, "reference": None, "difference": None,
            "relative_change_pct": None, "n7": 0, "n28": 0, "n_reference": 0,
            "series": series,
        }

    day_7 = last_day - timedelta(days=6)
    day_28 = last_day - timedelta(days=27)
    # Línea de comparación sin solapamiento: 28 días previos a los 7 recientes.
    ref_end = last_day - timedelta(days=7)
    ref_start = last_day - timedelta(days=34)

    def vals(from_day: date, to_day: date) -> list[float]:
        return [
            v for r in rows
            if from_day <= r["date"] <= to_day and _usable(r)
            if (v := _number(r[column])) is not None
        ]

    v7 = vals(day_7, last_day)
    v28 = vals(day_28, last_day)
    vref = vals(ref_start, ref_end)
    latest = next(
        (s["v"] for s in reversed(series) if s["date"] == last_day.isoformat()), None
    )
    a7 = mean(v7) if v7 else None
    a28 = mean(v28) if v28 else None
    # Referencia mínima razonable: siete noches válidas de 28 posibles.
    ref = mean(vref) if len(vref) >= 7 else None
    diff = a7 - ref if a7 is not None and ref is not None and len(v7) >= 3 else None
    pct = 100 * diff / ref if diff is not None and ref != 0 else None
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "origin": origin,
        "latest": latest,
        "mean7": a7,
        "mean28": a28,
        "reference": ref,
        "difference": diff,
        "relative_change_pct": pct,
        "n7": len(v7),
        "n28": len(v28),
        "n_reference": len(vref),
        "series": series,
    }


def report(
    conn: duckdb.DuckDBPyConnection, device_id: str, *, days: int = 90
) -> dict[str, Any]:
    if days not in (28, 90, 365):
        raise ValueError("Periodo no admitido: 28, 90 o 365")
    data = conn.execute(
        """SELECT local_sleep_date, sleep_min, rmssd_ms, rhr, resp_rate, spo2,
                  skin_temp, provider_recovery, score_state, calibrating,
                  quality, coalesce(night_check, 'ok') AS night_check
           FROM daily_metrics
           WHERE device_id = ? ORDER BY local_sleep_date DESC LIMIT ?""",
        [device_id, MAX_DAYS],
    ).fetchall()
    cols = (
        "date", "sleep_min", "rmssd_ms", "rhr", "resp_rate", "spo2",
        "skin_temp", "provider_recovery", "score_state", "calibrating",
        "quality", "night_check",
    )
    all_rows = [dict(zip(cols, row)) for row in reversed(data)]
    anchor = all_rows[-1]["date"] if all_rows else None
    cutoff = anchor - timedelta(days=days - 1) if anchor else None
    shown = [r for r in all_rows if cutoff is not None and r["date"] >= cutoff]
    good = sum(_usable(r) for r in shown)
    breakdown = {
        "high": sum(r["quality"] == "high" for r in shown),
        "fair": sum(r["quality"] == "fair" for r in shown),
        "excluded": sum(r["quality"] not in VALID_QUALITY for r in shown),
        "night_flags": sum(r["night_check"] != "ok" for r in shown),
    }
    # Se consultan hasta 365 días para disponer de una referencia de 28 días
    # anteriores incluso si la ventana visual es de 28 días.
    metrics = [
        _metric(all_rows, key, column, label, unit, origin)
        for key, label, column, unit, origin in METRICS
    ]
    for item in metrics:
        item["series"] = [
            p for p in item["series"]
            if cutoff is not None and p["date"] >= cutoff.isoformat()
        ]
    return {
        "device_id": device_id,
        "source": "WHOOP · conexión directa",
        "days": days,
        "anchor_date": anchor.isoformat() if anchor else None,
        "first_date": shown[0]["date"].isoformat() if shown else None,
        "nights": len(shown),
        "usable_nights": good,
        "breakdown": breakdown,
        "metrics": metrics,
        "reference_method": (
            "Media de los 28 días anteriores a los últimos 7; mínimo 7 noches válidas. "
            "Comparación: media reciente de 7 días, mínimo 3. "
            "Se excluyen noches con calidad inválida o revisión de datos pendiente."
        ),
        "caution": (
            "Variaciones estadísticas, no diagnósticos ni instrucciones médicas. "
            "Las lecturas de WHOOP son estimaciones del dispositivo; "
            "la puntuación Recovery es un modelo propietario."
        ),
    }
