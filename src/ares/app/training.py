"""Read-only training explorer from Tredict's full-activity local archive.

The connector saves raw JSON. Here we expose only workout fields required for
performance analysis; GPS coordinates and athlete notes remain in the local DB,
never exposed by these views. No invented threshold or fitness metrics.
"""

from __future__ import annotations

import json
import math
from typing import Any

import duckdb

from ..connectors.tredict import ACTIVITY_ID_RE
from . import training_analysis


def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = float(v)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def _raw_details(conn: duckdb.DuckDBPyConnection, limit: int = 300) -> list[dict]:
    rows = conn.execute(
        """SELECT body FROM raw_payload
           WHERE source='tredict' AND endpoint='activity_detail'
           ORDER BY fetched_at DESC LIMIT ?""",
        [limit],
    ).fetchall()
    seen: set[str] = set()
    items = []
    for (body,) in rows:
        rec = json.loads(body) if isinstance(body, str) else body
        ident = str(rec.get("_id") or rec.get("id") or "")
        if not ACTIVITY_ID_RE.fullmatch(ident) or ident in seen:
            continue
        seen.add(ident)
        items.append(rec)
    return sorted(items, key=lambda rec: str(rec.get("date", "")), reverse=True)


def _summary(rec: dict[str, Any]) -> dict[str, Any]:
    s = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}
    d = num(s.get("distance"))  # metros
    duration = num(s.get("duration"))  # segundos
    pace = num(s.get("pace"))  # segundos/km en Tredict
    derived = False
    if pace is None and d is not None and d > 0 and duration is not None and duration > 0:
        pace = 1000 * duration / d
        derived = True
    return {
        "id": str(rec.get("_id") or rec.get("id")),
        "date": str(rec.get("date", ""))[:10],
        "sport": str(rec.get("sportType") or "—"),
        "sub_sport": str(rec.get("subSportType") or ""),
        "title": str(rec.get("title") or rec.get("sportType") or "Entrenamiento")[:160],
        "distance_m": d,
        "duration_s": duration,
        "pace_s_km": pace if pace is not None and pace > 0 else None,
        "pace_calculated": derived,
        "avg_hr": num(s.get("heartrate")),
        "max_hr": num(s.get("heartrateMax")),
        "avg_power": num(s.get("power")),
        "cadence": num(s.get("cadence")),
        "vo2max_provider": num(s.get("vo2max")),
        "attribution": str(rec.get("attribution") or "Tredict"),
        "laps_count": len(rec["laps"]) if isinstance(rec.get("laps"), list) else 0,
        "has_series": isinstance(rec.get("seriesSampled"), dict),
    }


def list_sessions(conn: duckdb.DuckDBPyConnection, limit: int = 20) -> list[dict[str, Any]]:
    if limit < 1 or limit > 50:
        raise ValueError("limit debe estar entre 1 y 50")
    return [_summary(item) for item in _raw_details(conn)[:limit]]


def _downsample(values: Any, sample_s: Any, max_points: int = 250) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    sample = num(sample_s)
    if sample is None or not (0 < sample <= 300):
        return []
    # Muestreo uniforme para visualización, preservando SIEMPRE el primer
    # y último punto. El motor de análisis trabaja con la serie completa.
    count = min(max_points, len(values))
    if count < 2:
        indexes = [0] if values else []
    else:
        indexes = [round(j * (len(values) - 1) / (count - 1)) for j in range(count)]
    return [{"second": round(i * sample), "v": num(values[i])}
            for i in indexes]


def session(conn: duckdb.DuckDBPyConnection, activity_id: str) -> dict[str, Any] | None:
    if not ACTIVITY_ID_RE.fullmatch(activity_id):
        return None
    selected = next(
        (item for item in _raw_details(conn) if
         str(item.get("_id") or item.get("id")) == activity_id),
        None,
    )
    if selected is None:
        return None
    laps = []
    for i, raw in enumerate(selected.get("laps") or []):
        if not isinstance(raw, dict):
            continue
        laps.append({
            "number": i + 1,
            "distance_m": num(raw.get("distance")),
            "duration_s": num(raw.get("duration")),
            "pace_s_km": num(raw.get("pace")),
            "avg_hr": num(raw.get("heartrate")),
            "max_hr": num(raw.get("heartrateMax")),
            "power": num(raw.get("power")),
            "cadence": num(raw.get("cadence")),
            "trigger": str(raw.get("lapTrigger") or ""),
        })
        if len(laps) >= 300:
            break
    data = selected.get("seriesSampled")
    values = data.get("data", {}) if isinstance(data, dict) else {}
    period = data.get("sampleSize") if isinstance(data, dict) else None
    if not isinstance(values, dict):
        values = {}
    summary = _summary(selected)
    sport = summary["sport"]
    analysis = {
        "quality": training_analysis.series_quality(values, period, summary["duration_s"]),
        "drift": training_analysis.decoupling_proxy(
            values, period, summary["duration_s"], sport=sport
        ),
        "laps": training_analysis.lap_consistency(laps, sport=sport),
    }
    return {
        **summary,
        "analysis": analysis,
        "laps": laps,
        "sample_seconds": num(period),
        "series": {
            "heartrate": _downsample(values.get("heartrate"), period),
            "speed": _downsample(values.get("speed"), period),
            "power": _downsample(values.get("power"), period),
            "cadence": _downsample(values.get("cadence"), period),
        },
        "method": (
            "Lecturas y vueltas suministradas por Tredict; no se inventan "
            "muestras ausentes. Ritmo de resumen en segundos/km y distancia en metros."
        ),
    }
