"""ARES Marathon Lab · plan vigente y Fueling ARES v1.0, ambos con procedencia.

El snapshot fue seleccionado explícitamente de la carpeta 000/ARES/01 RUNNING/
MARATÓN (fuera de Old), el 14/10/2026. No hay conexión de Drive en el
servidor local: nunca presentarlo como sincronización automática.

Los rangos nutricionales son orientativos, no una dieta individual exacta.
No infiere cumplimiento del plan de una actividad sin vinculación validada.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

FILE = Path(__file__).with_name("plan_oct_dec_2026.json")
BANDS = {
    "LOW": (3.0, 4.0),
    "MEDIUM": (4.0, 5.0),
    "HIGH": (5.0, 6.0),
    "VERY HIGH": (6.0, 7.0),
}
ORDER = tuple(BANDS)
FUELING_SOURCE = "Fueling ARES — Sistema Maestro de Nutrición v1.0 (19/09/2026)"


def _snapshot(source_file: Path | None = None) -> dict[str, Any]:
    file = source_file if source_file is not None and source_file.is_file() else FILE
    with file.open(encoding="utf-8") as f:
        obj = json.load(f)
    if obj.get("format") != "ares-marathon-plan-v1":
        raise ValueError("Snapshot ARES desconocido")
    weeks = obj.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        raise ValueError("Plan sin semanas")
    for week in weeks:
        rows = week.get("sessions", [])
        if len(rows) != 7 or len({r["date"] for r in rows}) != 7:
            raise ValueError("Semana incompleta o fechas duplicadas")
    return obj


def _kind(s: dict[str, Any]) -> str:
    if s["type"] == "DESCANSO":
        return "rest"
    if s["type"] == "LARGO":
        return "long"
    if s["type"] == "MLR":
        return "medium_long"
    if s["type"] == "CALIDAD":
        return "quality"
    return "easy"


def _base_level(session: dict[str, Any]) -> str:
    kind = _kind(session)
    mins = session["duration_min"]
    if kind == "long" and mins > 120:
        return "VERY HIGH"
    if kind in {"quality", "medium_long"} or mins >= 90:
        return "HIGH"
    if kind == "rest" or mins < 45:
        return "LOW"
    return "MEDIUM"


def _preload_level(session: dict[str, Any] | None) -> str:
    if session is None:
        return "LOW"
    kind = _kind(session)
    if kind == "long" and session["duration_min"] > 135:
        return "VERY HIGH"
    if kind in {"long", "medium_long", "quality"}:
        return "HIGH"
    return "LOW"


def _max_level(a: str, b: str) -> str:
    return ORDER[max(ORDER.index(a), ORDER.index(b))]


def _intra(session: dict[str, Any]) -> dict[str, Any]:
    import re

    prescribed = session.get("during_fuel") or ""
    m = re.search(r"(\d+)(?:\s*[-–]\s*(\d+))?\s*g\s*/\s*h", prescribed, re.I)
    if m:
        return {"g_per_hour": [int(m[1]), int(m[2] or m[1])],
                "basis": "EXCEL_MAESTRO", "text": prescribed}
    mins = session["duration_min"]
    kind = _kind(session)
    if kind == "rest":
        range_ = [0, 0]
    elif kind == "easy" and mins < 60:
        range_ = [0, 0]
    elif kind == "quality" and mins <= 75:
        range_ = [20, 40]
    elif mins < 75:
        range_ = [0, 20]
    elif mins <= 100:
        range_ = [30, 50]
    elif mins <= 120:
        range_ = [40, 60]
    else:
        range_ = [60, 90]
    return {
        "g_per_hour": range_, "basis": "FUELING_V1_GUIDELINE",
        "text": (
            "Rango general del protocolo; NO sustituye una pauta específica "
            "ni autoriza a aumentar de golpe la dosis tolerada."
        ),
    }


def _post_rice(session: dict[str, Any]) -> list[int] | None:
    kind = _kind(session)
    mins = session["duration_min"]
    if kind == "rest":
        return None
    if kind == "long" and mins > 120:
        return [250, 350]
    if kind == "medium_long":
        return [230, 300]
    if kind == "quality":
        return [220, 280]
    if mins <= 45:
        return [180, 180]
    return [180, 220]


def _day(
    s: dict[str, Any], next_s: dict[str, Any] | None, weight_kg: float | None
) -> dict[str, Any]:
    base = _base_level(s)
    preload = _preload_level(next_s)
    level = _max_level(base, preload)
    lo, hi = BANDS[level]
    nutr: dict[str, Any] = {
        "category": level,
        "carbs_g_kg": [lo, hi],
        "carbs_g": [round(lo * weight_kg), round(hi * weight_kg)] if weight_kg else None,
        "weight_kg_used": weight_kg,
        "preload": ORDER.index(preload) > ORDER.index(base),
        "preload_for": next_s["date"] if next_s and preload != "LOW" else None,
        "during": _intra(s),
        "post_rice_cooked_g": _post_rice(s),
        "protein_g_kg": 1.8,
        "protein_g": round(1.8 * weight_kg) if weight_kg else None,
        "fat_g": [60, 75],
        "hydration": (
            "Al levantarte: 300–400 ml. En calidad o largo: otros 200–300 ml "
            "antes según tolerancia, sin forzar un volumen fijo. Durante largo: "
            "ajustar a sed y tasa de sudoración, no beber por obligación."
        ),
        "sodium_mg_h": [300, 600] if _kind(s) in {"long", "medium_long"} else None,
        "main_meal": (
            "En víspera de calidad/MLR/largo: concentrar carbohidratos "
            "en desayuno tras correr y comida, sin cena voluminosa."
            if preload != "LOW"
            else "Priorizar recuperación y comidas habituales; hidratos según carga."
        ),
        "post_strength": (
            "Tras fuerza del martes: el maestro especifica 35–40 g proteína "
            "en los 45 minutos siguientes."
            if s.get("strength_min") else None
        ),
    }
    return {**s, "nutrition": nutr}


def plan(
    *,
    week: str | None = None,
    today: date | None = None,
    tz: str = "Europe/Madrid",
    weight_kg: float | None = None,
    source_file: Path | None = None,
) -> dict[str, Any]:
    """Semana vigente o seleccionada; la fuente es un snapshot trazable."""
    p = _snapshot(source_file)
    weeks = p["weeks"]
    all_sessions = [day for w in weeks for day in w["sessions"]]
    if weight_kg is not None and (
        isinstance(weight_kg, bool) or not math.isfinite(weight_kg)
        or not 35 <= weight_kg <= 250
    ):
        raise ValueError("Peso configurado no plausible")
    if today is None:
        today = datetime.now(ZoneInfo(tz)).date()
    choice = next(
        (w for w in weeks if w["start"] <= today.isoformat() <= w["end"]), None
    ) if week is None else next((w for w in weeks if w["id"] == week), None)
    if choice is None:
        # Nunca asignar automáticamente entrenamientos de otro periodo.
        return {
            "available": False,
            "reason": "Fuera de las fechas de este snapshot. Se debe importar un plan vigente.",
            "source": p["source_name"],
            "source_url": p["source_url"],
            "source_version": p["source_version"],
            "imported_at": p["imported_at"],
            "weeks": [{"id": w["id"], "start": w["start"], "end": w["end"]} for w in weeks],
            "today": today.isoformat(),
        }
    by_date = {s["date"]: s for s in all_sessions}
    days = []
    for s in choice["sessions"]:
        # Para precargar se consulta la sesión del día natural siguiente.
        following = date.fromordinal(date.fromisoformat(s["date"]).toordinal() + 1).isoformat()
        days.append(_day(s, by_date.get(following), weight_kg))
    total_intra_min, total_intra_max = 0.0, 0.0
    for s in days:
        lo, hi = s["nutrition"]["during"]["g_per_hour"]
        total_intra_min += lo * s["duration_min"] / 60
        total_intra_max += hi * s["duration_min"] / 60
    return {
        "available": True,
        "week": choice["id"],
        "start": choice["start"],
        "end": choice["end"],
        "today": today.isoformat(),
        "days": days,
        "run_minutes": choice["run_minutes"],
        "run_km_approx": choice["run_km_approx"],
        "strength_sessions": sum(bool(s.get("strength_min")) for s in days),
        "intra_training_carbs_g_week": [
            round(total_intra_min), round(total_intra_max)
        ],
        "weight_kg": weight_kg,
        "source": p["source_name"],
        "source_version": p["source_version"],
        "source_url": p["source_url"],
        "source_name": p["source_name"],
        "source_sha256": p.get("source_sha256"),
        "snapshot_date": p["imported_at"],
        "sync": ("SNAPSHOT_LOCAL_VERIFIED_NO_LIVE_DRIVE"
                 if source_file is not None and source_file.is_file()
                 else "SNAPSHOT_MANUAL_NO_LIVE_DRIVE"),
        "fueling_source": FUELING_SOURCE,
        "fueling_source_url": p["fueling_source_url"],
        "weeks": [{"id": w["id"], "start": w["start"], "end": w["end"]} for w in weeks],
        "training_rules": p["rules"],
        "caveat": (
            "Plan PRESCRITO, no se supone ejecutado. Distancia estimada. "
            "Los rangos de carbohidratos son orientativos y dependen de "
            "la tolerancia gastrointestinal, el peso actualizado y la ingesta real. "
            "La pauta específica de geles del Excel prevalece sobre rangos generales."
        ),
    }
