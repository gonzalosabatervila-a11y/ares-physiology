"""ARES Execution Intelligence: prescripción, observación y contexto nocturno.

Nunca equipara la coincidencia por fecha con un entrenamiento cumplido.
No deduce que la sesión haya provocado un cambio de HRV/FC/sueño.
Cada ejecución observada se deduplica por el identificador Tredict.
Las muestras solo se leen en local; nunca se exponen GPS/notas.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from . import training, training_context

MAX_RAW = 1500
RUN_SPORTS = {"running", "run", "trail_running", "treadmill", "outdoor_run", "indoor_run"}


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None and d.utcoffset() is not None else None


def _logged_runs(
    conn: duckdb.DuckDBPyConnection, start: str, end: str, tz: str
) -> dict[str, list[dict[str, Any]]]:
    """Últimos resúmenes de cada actividad, priorizando el detalle.

    Se lee un día adicional a cada lado para evitar desplazar una
    carrera nocturna por la fecha UTC usada en raw_payload.
    """
    start_day = date.fromisoformat(start) - timedelta(days=1)
    end_day = date.fromisoformat(end) + timedelta(days=1)
    rows = conn.execute(
        """SELECT endpoint, body FROM raw_payload
           WHERE source='tredict' AND endpoint IN ('activity','activity_detail')
           AND day BETWEEN ? AND ?
           ORDER BY fetched_at DESC LIMIT ?""",
        [start_day, end_day, MAX_RAW],
    ).fetchall()
    by_id: dict[str, dict[str, Any]] = {}
    for endpoint, body in rows:
        try:
            rec = json.loads(body) if isinstance(body, str) else body
            if not isinstance(rec, dict):
                continue
            ident = str(rec.get("_id") or rec.get("id") or "")
            if not training.ACTIVITY_ID_RE.fullmatch(ident):
                continue
            session = training._summary(rec)
            sport = session["sport"].lower().strip()
            if sport not in RUN_SPORTS:
                continue
            instant = _instant(session["start_utc"])
            if instant is None:
                # Sin hora/tz no se asigna una ejecución por fecha especulativa.
                continue
            local_day = instant.astimezone(ZoneInfo(tz)).date().isoformat()
            if not start <= local_day <= end:
                continue
            entry = {
                "id": ident, "date": local_day,
                "start_utc": instant.isoformat(),
                "title": session["title"],
                "duration_s": session["duration_s"],
                "distance_m": session["distance_m"],
                "avg_hr": session["avg_hr"],
                "has_detail": endpoint == "activity_detail",
                "source": "Tredict · COROS declarado",
            }
            previous = by_id.get(ident)
            if previous is None or (entry["has_detail"] and not previous["has_detail"]):
                by_id[ident] = entry
        except (TypeError, ValueError, KeyError):
            # Evento corrupto -> no se contabiliza como ejecución.
            continue
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in by_id.values():
        out.setdefault(entry["date"], []).append(entry)
    for entries in out.values():
        entries.sort(key=lambda r: r["start_utc"])
    return out


def _safe_context(
    conn: duckdb.DuckDBPyConnection,
    device_id: str,
    runs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    # Con >1 sesiones el cambio nocturno responde al DÍA y no se
    # atribuye a una sola sesión.
    if len(runs) != 1:
        return None
    run = runs[0]
    duration = run.get("duration_s")
    if duration is None or not 0 < duration < 86400:
        return None
    response = training_context.training_night_context(
        conn, device_id, run["start_utc"], duration,
    )
    if not response.get("available"):
        return None
    return {
        "before": response["before"],
        "after": response["after"],
        "difference": response["difference"],
        "method": response["method"],
        "interpretation": (
            "Comparación descriptiva entre dos noches WHOOP válidas. "
            "No demuestra causalidad ni autoriza ajustes automáticos del plan."
        ),
    }


def execution(
    conn: duckdb.DuckDBPyConnection,
    days: list[dict[str, Any]],
    *,
    device_id: str,
    tz: str = "Europe/Madrid",
    today: date,
) -> dict[str, Any]:
    if not days:
        return {"days": {}, "summary": {"recorded": 0, "unverified": 0}}
    observations = _logged_runs(conn, days[0]["date"], days[-1]["date"], tz)
    per_day: dict[str, Any] = {}
    recorded = 0
    with_context = 0
    observed_minutes = 0.0
    observed_km = 0.0
    for s in days:
        day = s["date"]
        rows = observations.get(day, [])
        if rows:
            recorded += 1
            status = "observed_unverified" if s["type"] != "DESCANSO" else "rest_day_activity"
        elif day > today.isoformat():
            status = "future"
        else:
            # Sin evento no sabemos si no corrió o si la fuente está atrasada.
            status = "no_record_found"
        duration = sum(
            r["duration_s"] for r in rows
            if isinstance(r["duration_s"], (float, int))
            and not isinstance(r["duration_s"], bool) and 0 < r["duration_s"] < 86400
        )
        distance = sum(
            r["distance_m"] for r in rows
            if isinstance(r["distance_m"], (float, int))
            and not isinstance(r["distance_m"], bool) and 0 < r["distance_m"] < 200000
        )
        observed_minutes += duration / 60
        observed_km += distance / 1000
        context = _safe_context(conn, device_id, rows)
        with_context += bool(context)
        plan_mins = s.get("duration_min")
        comparable = bool(
            rows and len(rows) == 1 and isinstance(plan_mins, (float,int))
            and plan_mins > 0 and duration > 0
        )
        per_day[day] = {
            "status": status,
            "verified_completion": False,
            "source": "Tredict · COROS declarado",
            "count": len(rows),
            "activities": rows,
            "observed_minutes": round(duration / 60, 1) if rows else None,
            "observed_km": round(distance / 1000, 2) if distance else None,
            "duration_difference_min": (
                round(duration / 60 - plan_mins, 1) if comparable else None
            ),
            "duration_comparison": (
                "Diferencia de duración descriptiva, NO acredita bloques ni zonas."
                if comparable else None
            ),
            "night_context": context,
        }
    return {
        "days": per_day,
        "summary": {
            "days_with_running_activity": recorded,
            "days_with_night_context": with_context,
            "recorded_run_minutes": round(observed_minutes),
            "recorded_run_km": round(observed_km, 2),
            "verified_prescriptions": 0,
            "method": (
                "Registros Tredict deduplicados por identificador, con hora "
                "convertida a Europe/Madrid. No se equiparan por fecha a sesiones "
                "cumplidas. La comparación WHOOP usa los límites reales del sueño "
                "y se muestra solo si hay una única carrera en ese día."
            ),
        },
    }
