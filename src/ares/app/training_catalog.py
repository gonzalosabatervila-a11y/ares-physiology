"""Calendario ARES: COROS/Tredict para correr, WHOOP para el resto.

La pertenencia a COROS se declara por configuración del usuario: Tredict no
certifica el modelo de reloj en todos los registros. No inferir rucking a
partir de una caminata simple, ni mezclar datos de sensores diferentes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import duckdb

from . import training, training_comparison, training_context

RECENT_LIMIT = 1200
WHOOP_NAMES = {
    "walking": "Caminar",
    "walk": "Caminar",
    "hiking": "Senderismo",
    "hike": "Senderismo",
    "rucking": "Rucking",
    "ruck": "Rucking",
    "weightlifting": "Fuerza",
    "functional_fitness": "Entrenamiento funcional",
    "cycling": "Bicicleta",
    "swimming": "Natación",
    "yoga": "Yoga",
}
RUN_NAMES = {"running", "run", "trail_running", "treadmill", "outdoor_run", "indoor_run"}


def _dt(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        v = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return v if v.tzinfo is not None and v.utcoffset() is not None else None


def _date(instant: str, tz: str) -> str:
    d = _dt(instant)
    return d.astimezone(ZoneInfo(tz)).date().isoformat() if d else str(instant)[:10]


def _whoop_sessions(
    conn: duckdb.DuckDBPyConnection, device_id: str, tz: str
) -> list[dict[str, Any]]:
    # Read only the active wearer's imported WHOOP workout events.
    rows = conn.execute(
        """SELECT body FROM raw_payload WHERE source='whoop'
           AND endpoint='workout' AND device_id = ?
           ORDER BY fetched_at DESC LIMIT ?""",
        [device_id, RECENT_LIMIT],
    ).fetchall()
    seen: set[str] = set()
    out = []
    for (body,) in rows:
        rec = json.loads(body) if isinstance(body, str) else body
        ident = str(rec.get("id") or "")
        if not training.ACTIVITY_ID_RE.fullmatch(ident) or ident in seen:
            continue
        seen.add(ident)
        sport = str(rec.get("sport_name") or "").strip().lower().replace(" ", "_")
        # Running comes from COROS via Tredict, never duplicate WHOOP runs.
        if sport in RUN_NAMES or "run" in sport:
            continue
        start, end = _dt(rec.get("start")), _dt(rec.get("end"))
        if start is None or end is None or end <= start:
            continue
        duration = (end - start).total_seconds()
        if duration > 48 * 3600:
            continue
        score = rec.get("score") if isinstance(rec.get("score"), dict) else {}
        out.append({
            "id": ident,
            "date": _date(rec["start"], tz),
            "start_utc": start.isoformat(),
            "sport": sport or "other",
            "title": WHOOP_NAMES.get(sport, (sport or "Actividad").replace("_", " ").capitalize()),
            "distance_m": None, "duration_s": duration, "elapsed_s": duration,
            "pace_s_km": None, "pace_calculated": False,
            "avg_hr": training.num(score.get("average_heart_rate")),
            "max_hr": training.num(score.get("max_heart_rate")),
            "avg_power": None, "cadence": None, "vo2max_provider": None,
            "laps_count": 0, "has_series": False,
            "score_strain": training.num(score.get("strain")),
            "attribution": "WHOOP · sesión registrada",
            "group": "other", "source": "whoop", "has_detail": True,
            "source_verified": True,
        })
    return out


def _tredict_sessions(
    conn: duckdb.DuckDBPyConnection, tz: str
) -> list[dict[str, Any]]:
    details = training.list_sessions(conn, limit=50)
    seen = {r["id"] for r in details}
    out = []
    for rec in details:
        x = {**rec, "group": "running" if rec["sport"] == "running" else "other",
             "source": "tredict", "has_detail": True, "source_verified": False,
             "attribution": "COROS vía Tredict · origen declarado",
             "start_utc": rec.get("date", "")}
        out.append(x)
    rows = conn.execute(
        """SELECT body FROM raw_payload WHERE source='tredict'
           AND endpoint='activity' ORDER BY fetched_at DESC LIMIT ?""",
        [RECENT_LIMIT],
    ).fetchall()
    for (body,) in rows:
        rec = json.loads(body) if isinstance(body, str) else body
        ident = str(rec.get("id") or rec.get("_id") or "")
        if not training.ACTIVITY_ID_RE.fullmatch(ident) or ident in seen:
            continue
        seen.add(ident)
        summary = rec.get("summary")
        if not isinstance(summary, dict):
            summary = {k: rec[k] for k in ("duration", "durationTotal", "distance",
                                          "pace", "heartrate", "heartrateMax", "power",
                                          "cadence") if k in rec}
        shaped = {"_id": ident, **rec, "summary": summary}
        normalized = training._summary(shaped)
        normalized["date"] = _date(str(rec.get("date", "")), tz)
        out.append({
            **normalized, "group": "running" if normalized["sport"] == "running" else "other",
            "source": "tredict", "has_detail": False, "source_verified": False,
            "start_utc": str(rec.get("date") or ""),
            "attribution": "COROS vía Tredict · origen declarado",
        })
    return out


def catalog(
    conn: duckdb.DuckDBPyConnection,
    device_id: str,
    *,
    tz: str = "Europe/Madrid",
    category: str = "running",
    limit: int = 20,
) -> dict[str, Any]:
    if category not in {"running", "other"}:
        raise ValueError("category debe ser running u other")
    if not 1 <= limit <= 50:
        raise ValueError("limit debe estar entre 1 y 50")
    whoop = _whoop_sessions(conn, device_id, tz)
    all_tredict = _tredict_sessions(conn, tz)
    # WHOOP is primary for non-running; skip the COROS/Tredict duplicate if
    # timestamps are within 15 minutes and the events belong to the same day.
    cleaned = []
    for item in all_tredict:
        if item["group"] == "other":
            date_a = _dt(item.get("start_utc"))
            matches_whoop = any(
                date_a is not None and (date_b := _dt(w.get("start_utc"))) is not None
                and abs((date_a - date_b).total_seconds()) <= 900
                for w in whoop
            )
            if matches_whoop:
                continue
        cleaned.append(item)
    all_items = cleaned + whoop
    all_items.sort(key=lambda x: x.get("start_utc") or x.get("date", ""), reverse=True)
    running = [x for x in all_items if x["group"] == "running"]
    other = [x for x in all_items if x["group"] == "other"]
    chosen = running if category == "running" else other
    # Comparisons only from detailed running records (not incomplete summaries).
    comparable = [x for x in running if x["has_detail"] and x.get("pace_s_km")]
    return {
        "category": category,
        "counts": {"running": len(running), "other": len(other)},
        "sessions": chosen[:limit],
        "comparisons": training_comparison.compare(comparable) if category == "running" else [],
        "source": "COROS vía Tredict · correr / WHOOP · otros",
        "source_caveat": (
            "COROS se declara como origen de carrera, no puede certificarse "
            "a partir del listado de Tredict. Caminar no significa rucking "
            "salvo cuando WHOOP identifica expresamente esa actividad."
        ),
    }


def detail(
    conn: duckdb.DuckDBPyConnection, activity_id: str,
    *,
    device_id: str, tz: str = "Europe/Madrid",
) -> dict[str, Any] | None:
    existing = training.session(conn, activity_id, device_id=device_id)
    if existing is not None:
        return {
            **existing, "source": "tredict",
            "group": "running" if existing["sport"] == "running" else "other",
            "has_detail": True, "source_verified": False,
        }
    item = next((w for w in _whoop_sessions(conn, device_id, tz)
                 if w["id"] == activity_id), None)
    if item is None:
        item = next((x for x in _tredict_sessions(conn, tz)
                     if x["id"] == activity_id), None)
    if item is None:
        return None
    ctx = training_context.training_night_context(
        conn, device_id, item.get("start_utc", ""), item.get("elapsed_s") or item.get("duration_s")
    )
    return {
        **item, "laps": [], "sample_seconds": None,
        "series": {"heartrate": [], "speed": [], "power": [], "cadence": []},
        "analysis": None, "hr_zones": None, "night_context": ctx,
        "method": (
            "Datos resumen del proveedor. No hay series de sensores ni vueltas "
            "para este evento; no se inventan detalles. "
            "Importa el entrenamiento completo de Tredict cuando esté disponible."
        ),
    }
