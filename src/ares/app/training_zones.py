"""Tredict's dated HR-zone snapshots and time distributions, read-only.

This does not recalculate the user's HR zones retrospectively. Values and
zone boundaries are supplied by Tredict as they were on the activity date.
"""
from __future__ import annotations

from typing import Any

from .training_analysis import finite


def heart_rate_zones(activity: dict[str, Any]) -> dict[str, Any]:
    summary = activity.get("summary")
    current = activity.get("currentZones")
    if not isinstance(summary, dict) or not isinstance(current, dict):
        return {"available": False, "zones": [], "reason": "Sin zonas históricas completas."}
    distribution = summary.get("zonesDistribution")
    if not isinstance(distribution, dict):
        return {"available": False, "zones": [], "reason": "Sin distribución por zonas."}
    durations = distribution.get("heartrate")
    definitions = current.get("heartrate")
    if not isinstance(durations, list) or not isinstance(definitions, list):
        return {"available": False, "zones": [], "reason": "Sin zonas de FC con duración."}
    if not durations or len(durations) != len(definitions):
        return {"available": False, "zones": [], "reason": "Definiciones y duraciones no coinciden."}
    if len(durations) > 15:
        return {"available": False, "zones": [], "reason": "Demasiadas zonas."}
    values = [finite(x) for x in durations]
    if any(x is None or x < 0 or x > 172800 for x in values):
        return {"available": False, "zones": [], "reason": "Duración de zona inválida."}
    total = sum(values)
    session = finite(summary.get("duration"))
    if total <= 0 or (session and total > session * 1.1):
        return {"available": False, "zones": [], "reason": "Cobertura temporal incompatible."}
    result = []
    for i, (zone, seconds) in enumerate(zip(definitions, values)):
        if not isinstance(zone, dict):
            return {"available": False, "zones": [], "reason": "Definición de zona inválida."}
        result.append({
            "name": str(zone.get("name") or f"Z{i+1}")[:30],
            "min_hr": finite(zone.get("from")),
            "max_hr": finite(zone.get("to")),
            "seconds": round(seconds),
            "percent_recorded": round(100 * seconds / total, 1),
        })
    return {
        "available": True,
        "zones": result,
        "source": "CALC · ARES sobre distribución y umbrales Tredict",
        "recorded_seconds": round(total),
        "coverage_pct": round(100 * total / session, 1) if session and session > 0 else None,
        "method": (
            "Distribución temporal de FC calculada por Tredict y zonas vigentes "
            "en la fecha de la actividad. Porcentajes sobre segundos clasificados, "
            "no necesariamente sobre toda la duración."
        ),
    }
