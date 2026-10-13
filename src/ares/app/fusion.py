"""Comparación de métricas WHOOP e Intervals.icu por fecha de sueño local.

Solo consulta datos persistidos; nunca escribe ni sustituye la serie original.
La integración de COROS a través de Intervals.icu se declara en la configuración,
no se puede verificar la identidad del dispositivo en el payload de wellness.
La media de rMSSD es EXPLORATORIA: las ventanas y algoritmos de ambos
fabricantes pueden diferir. No alimenta decisiones de entrenamiento.
"""

from __future__ import annotations

import math
from typing import Any

import duckdb


# Valores plausibles iniciales, no umbrales médicos.
RANGES = {
    "sleep_min": (120.0, 960.0),
    "rhr": (25.0, 140.0),
    "hrv": (5.0, 300.0),
}
METRICS = ("sleep_min", "rhr", "hrv")
VALID_QUALITIES = {"high", "fair"}


def _valid(raw: Any, metric: str) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    lo, hi = RANGES[metric]
    return value if math.isfinite(value) and lo <= value <= hi else None


def combine(
    conn: duckdb.DuckDBPyConnection,
    device_id: str,
    intervals_days: list[dict[str, Any]],
    *,
    source_device: str = "COROS",
    limit: int = 90,
) -> dict[str, Any]:
    """Promedia pares del mismo día, sin relleno de fechas ni extrapolación.

    quality excluida en WHOOP -> no hay media; el valor original se muestra
    solo como dato de contexto. Si el valor COROS no consta ese día, no
    usamos el día anterior. En ningún caso se mezclan recovery y CTL.
    """
    rows = conn.execute(
        """SELECT local_sleep_date, sleep_min, rmssd_ms, rhr, quality
           FROM daily_metrics WHERE device_id = ?
           ORDER BY local_sleep_date DESC LIMIT ?""",
        [device_id, limit],
    ).fetchall()
    other = {d["date"]: d for d in intervals_days}
    latest_date = rows[0][0].isoformat() if rows else None
    pairs: dict[str, int] = {m: 0 for m in METRICS}
    matched_any = 0
    latest: dict[str, Any] | None = None

    for day, sleep_min, rmssd, rhr, quality in rows:
        date = day.isoformat()
        coros = other.get(date)
        whoop_valid = quality in VALID_QUALITIES
        raw = {
            "sleep_min": (sleep_min, None),
            "rhr": (rhr, coros.get("restingHR") if coros else None),
            "hrv": (rmssd, coros.get("hrv") if coros else None),
        }
        # sleepSecs viene en segundos: comprobar la plausibilidad *después*
        # de convertirlo a minutos, no en el valor original.
        if coros is not None:
            secs = coros.get("sleepSecs")
            try:
                minutes = float(secs) / 60 if secs is not None and not isinstance(secs, bool) else None
            except (ValueError, TypeError):
                minutes = None
            raw["sleep_min"] = (sleep_min, minutes)
        entries: dict[str, Any] = {}
        any_pair = False
        for metric, (from_whoop, from_intervals) in raw.items():
            w = _valid(from_whoop, metric)
            c = _valid(from_intervals, metric)
            if not whoop_valid:
                w = None  # no contribuir a medias con noches WHOOP excluidas
            both = w is not None and c is not None
            if both:
                pairs[metric] += 1
                any_pair = True
            entries[metric] = {
                "whoop": w,
                "intervals": c,
                "mean": (w + c) / 2 if both else None,
                "kind": "EXP" if metric == "hrv" else "CALC",
                "paired": both,
            }
        if any_pair:
            matched_any += 1
        if latest is None:
            latest = {
                "date": date,
                "whoop_quality": quality,
                "whoop_valid": whoop_valid,
                "intervals_available": coros is not None,
                "metrics": entries,
            }
    return {
        "source": "WHOOP + Intervals.icu",
        "intervals_device": source_device,
        "device_verified": False,
        "matched_days": matched_any,
        "metric_pairs": pairs,
        "whoop_days": len(rows),
        "latest_date": latest_date,
        "latest": latest,
        "hrv_experimental": True,
    }
