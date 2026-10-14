"""ARES Training Intelligence: conservative, transparent analysis of running streams.

Everything here is a *description* of a recorded session. Not a measured VO2max,
lactate threshold, readiness score, or diagnosis.

The decoupling proxy is only shown for reasonably steady, well-covered running.
For workouts with intervals, hills, pauses or missing samples it is suppressed.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any

MIN_DRIFT_DURATION = 40 * 60
TRIM_WARMUP_S = 10 * 60
TRIM_COOLDOWN_S = 5 * 60
MIN_VALID_PAIR_COVERAGE = 0.80
MAX_SPEED_CV = 0.10
MAX_HALF_SPEED_GAP = 0.05


def finite(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (ValueError, TypeError):
        return None
    return x if math.isfinite(x) else None


def _between(value: Any, lo: float, hi: float) -> float | None:
    x = finite(value)
    return x if x is not None and lo <= x <= hi else None


def series_quality(
    values: dict[str, Any], sample_seconds: Any, moving_seconds: Any
) -> dict[str, Any]:
    """Coverage over expected sensor samples, never treat a null as zero."""
    tick = _between(sample_seconds, 0.25, 60)
    duration = _between(moving_seconds, 30, 172800)
    if tick is None or duration is None:
        return {"sample_seconds": tick, "expected_samples": None,
                "hr_coverage_pct": None, "speed_coverage_pct": None,
                "paired_coverage_pct": None, "usable_for_drift": False,
                "reason": "Falta duración o frecuencia de muestreo válida."}
    expected = math.ceil(duration / tick)
    heartrate = values.get("heartrate")
    speed = values.get("speed")
    hr = heartrate if isinstance(heartrate, list) else []
    sp = speed if isinstance(speed, list) else []
    cap = min(expected, max(len(hr), len(sp)))
    valid_hr = sum(_between(v, 40, 220) is not None for v in hr[:expected])
    valid_sp = sum(_between(v, 0, 15) is not None for v in sp[:expected])
    paired = sum(
        _between(hr[i], 40, 220) is not None
        and _between(sp[i], 0, 15) is not None
        for i in range(min(expected, len(hr), len(sp)))
    )
    return {
        "sample_seconds": tick,
        "expected_samples": expected,
        "observed_samples": cap,
        "hr_coverage_pct": round(100 * valid_hr / expected, 1),
        "speed_coverage_pct": round(100 * valid_sp / expected, 1),
        "paired_coverage_pct": round(100 * paired / expected, 1),
        "usable_for_drift": paired / expected >= MIN_VALID_PAIR_COVERAGE,
        "reason": None if paired / expected >= MIN_VALID_PAIR_COVERAGE
                  else "Cobertura simultánea de pulso y velocidad insuficiente.",
    }


def decoupling_proxy(
    values: dict[str, Any], sample_seconds: Any, moving_seconds: Any,
    *, sport: str = "running", elapsed_seconds: Any = None,
) -> dict[str, Any]:
    """Cambio del cociente FC/velocidad entre mitades de un tramo casi uniforme.

    Se excluyen 10 min iniciales y 5 finales; resto dividido en dos mitades.
    No es la 'deriva cardíaca clínica'; puede variar con temperatura, GPS,
    elevación, alimentación, medición óptica y pendiente del terreno.
    """
    quality = series_quality(values, sample_seconds, moving_seconds)
    base: dict[str, Any] = {
        "available": False, "value_pct": None,
        "first": None, "second": None,
        "quality": quality,
        "method": "Cambio porcentual FC/velocidad entre mitades de un tramo estable.",
    }
    if sport != "running":
        return {**base, "reason": "Solo evaluado en carrera."}
    total = finite(elapsed_seconds)
    moving = finite(moving_seconds)
    if total is not None and moving is not None and total > 0:
        if moving <= 0 or (total - moving) / total > 0.03:
            return {**base, "reason": "Pausas superiores al 3 % del tiempo: sesiones no comparables."}
    tick = quality["sample_seconds"]
    duration = finite(moving_seconds)
    if tick is None or duration is None or duration < MIN_DRIFT_DURATION:
        return {**base, "reason": "Sesión demasiado corta o sin frecuencia de muestreo."}
    if not quality["usable_for_drift"]:
        return {**base, "reason": quality["reason"]}
    hr = values.get("heartrate") if isinstance(values.get("heartrate"), list) else []
    speed = values.get("speed") if isinstance(values.get("speed"), list) else []
    start, end = TRIM_WARMUP_S, duration - TRIM_COOLDOWN_S
    if end - start < 20 * 60:
        return {**base, "reason": "Tramo analizable insuficiente."}
    half = (start + end) / 2
    groups: list[list[tuple[float, float]]] = [[], []]
    coverage = [0, 0]
    valid = [0, 0]
    for i in range(math.ceil(duration / tick)):
        t = i * tick
        if t < start or t >= end:
            continue
        k = 0 if t < half else 1
        coverage[k] += 1
        h = _between(hr[i] if i < len(hr) else None, 55, 210)
        v = _between(speed[i] if i < len(speed) else None, 1.8, 7.5)
        if h is not None and v is not None:
            valid[k] += 1
            groups[k].append((h, v))
    if any(not total or n / total < MIN_VALID_PAIR_COVERAGE
           for total, n in zip(coverage, valid)):
        return {**base, "reason": "Pulso/ritmo insuficientes en una de las dos mitades."}
    mh = [mean(h for h, _ in group) for group in groups]
    mv = [mean(v for _, v in group) for group in groups]
    cvs = [pstdev([v for _, v in group]) / m
           for group, m in zip(groups, mv)]
    if max(cvs) > MAX_SPEED_CV:
        return {**base, "reason": "Variación de velocidad elevada: probablemente series o terreno irregular."}
    if abs(mv[1] / mv[0] - 1) > MAX_HALF_SPEED_GAP:
        return {**base, "reason": "Velocidad media de las dos mitades no comparable."}
    ratio_first = mh[0] / mv[0]
    ratio_second = mh[1] / mv[1]
    return {
        **base,
        "available": True,
        "value_pct": round((ratio_second / ratio_first - 1) * 100, 2),
        "first": {"hr": round(mh[0], 1), "speed_m_s": round(mv[0], 3),
                  "samples": valid[0]},
        "second": {"hr": round(mh[1], 1), "speed_m_s": round(mv[1], 3),
                   "samples": valid[1]},
        "reason": None,
        "caution": (
            "Indicador descriptivo EXP, no umbral ni diagnóstico. "
            "Excluye 10 min iniciales y 5 finales; exige ≥40 min, "
            "≥80 % de cobertura FC/velocidad, CV de velocidad ≤10 % "
            "en cada mitad y diferencia de velocidades medias ≤5 %."
        ),
    }


def lap_consistency(laps: list[dict[str, Any]], *, sport: str = "running") -> dict[str, Any]:
    """Variación de ritmo de laps comparables por distancia, sin inventar intervalos."""
    empty = {"available": False, "count": 0, "pace_cv_pct": None,
             "mean_pace_s_km": None, "reason": "No hay suficientes vueltas comparables."}
    if sport != "running":
        return {**empty, "reason": "Solo evaluado en carrera."}
    pts = []
    for lap in laps:
        distance = _between(lap.get("distance_m"), 200, 5000)
        duration = _between(lap.get("duration_s"), 30, 3600)
        if distance is None or duration is None:
            continue
        pace = 1000 * duration / distance
        if _between(pace, 120, 1200) is not None:
            pts.append((distance, pace))
    if len(pts) < 3:
        return empty
    # Grupo con más vueltas a una distancia comparable (±5 %), no mezclar
    # calentamientos largos con intervalos cortos.
    groups = [
        [(d, p) for d, p in pts if abs(d / target - 1) <= 0.05]
        for target, _ in pts
    ]
    chosen = max(groups, key=len)
    if len(chosen) < 3:
        return empty
    vals = [pace for _, pace in chosen]
    avg = mean(vals)
    return {
        "available": True,
        "count": len(vals),
        "mean_pace_s_km": round(avg, 1),
        "pace_cv_pct": round(100 * pstdev(vals) / avg, 2),
        "reason": None,
        "method": "Dispersión de ritmos de ≥3 vueltas de distancia ±5 %.",
        "caution": "CALC; no distingue automáticamente bloques de trabajo y recuperación.",
    }
