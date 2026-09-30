"""Lo que la app enseña, calculado solo a partir de la base (nunca escribe).

Principio de la UX v1: nada de puntuaciones inventadas. Cada valor lleva su etiqueta
(MED/CALC/EST/EXP) y su origen, y lo que aún no existe se dice tal cual («sin datos»,
«modo sombra»). Hoy solo hay intervals.icu y Tredict en la capa bruta; lo de la Loop
llegará cuando exista su conector.
"""

from __future__ import annotations

import json
import statistics as st
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb

from .. import jobs

NIGHTS_TARGET = 21  # noches válidas para salir del modo sombra
MIN_DAYS_FOR_RANGE = 7  # días mínimos para calcular un rango personal
RANGE_K = 0.5  # rango normal = media ± 0,5 DT (decisión de diseño ARES, ver plan)
FRESH_H, STALE_H = 12, 36


def _scalar(conn: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    return row[0] if row else None


def _load(body: Any) -> dict[str, Any]:
    return json.loads(body) if isinstance(body, str) else dict(body)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- intervals.icu


def intervals_days(conn: duckdb.DuckDBPyConnection, limit: int = 60) -> list[dict[str, Any]]:
    """Última versión guardada de cada día de bienestar, de más antiguo a más reciente."""
    rows = conn.execute(
        """SELECT day, body FROM raw_payload
           WHERE source = 'intervals' AND endpoint = 'wellness'
           QUALIFY row_number() OVER (PARTITION BY day ORDER BY fetched_at DESC, rowid DESC) = 1
           ORDER BY day DESC LIMIT ?""",
        [limit],
    ).fetchall()
    out = []
    for day, body in reversed(rows):
        rec = _load(body)
        out.append(
            {
                "date": day.isoformat(),
                "sleepSecs": _num(rec.get("sleepSecs")),
                "avgSleepingHR": _num(rec.get("avgSleepingHR")),
                "restingHR": _num(rec.get("restingHR")),
                "hrv": _num(rec.get("hrv")),
                "ctl": _num(rec.get("ctl")),
                "atl": _num(rec.get("atl")),
                "rampRate": _num(rec.get("rampRate")),
                "steps": _num(rec.get("steps")),
            }
        )
    return out


def _points(days: list[dict[str, Any]], key: str, scale: float = 1.0):
    return [(d["date"], None if d[key] is None else d[key] * scale) for d in days]


def personal_range(values: list[float]) -> dict[str, float] | None:
    if len(values) < MIN_DAYS_FOR_RANGE:
        return None
    mean = st.mean(values)
    sd = st.stdev(values)
    if sd == 0:
        sd = abs(mean) * 0.02 or 1.0
    return {"mean": mean, "sd": sd, "lo": mean - RANGE_K * sd, "hi": mean + RANGE_K * sd}


def fmt_hm(hours: float) -> str:
    minutes = int(round(hours * 60))
    return f"{minutes // 60}:{minutes % 60:02d}"


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def make_dial(
    key, label, points, fmt, tag, origin, note, *, agg="last", warn_below=True, judge=True
) -> dict[str, Any]:
    """`agg="mean7"`: el valor y la aguja son la media de los últimos 7 días, que es lo
    que compara la regla del plan con la franja de valores diarios (media ± 0,5 DT).
    Solo el lado «por debajo» se marca como aviso; «por encima» es informativo: las
    reglas lo interpretan con el resto de señales."""
    vals = [v for _, v in points if v is not None]
    base = {"key": key, "label": label, "tag": tag, "origin": origin, "note": note}
    if not vals:
        return {
            **base,
            "value": "—",
            "state": "sin datos",
            "level": "none",
            "p": None,
            "band": None,
            "date": None,
            "n": 0,
        }
    date = next(d for d, v in reversed(points) if v is not None)
    shown = st.mean(vals[-7:]) if agg == "mean7" else vals[-1]
    out = {**base, "value": fmt(shown), "date": date, "n": len(vals)}
    rng = personal_range(vals)
    if rng is None:
        return {
            **out,
            "state": f"sin rango ({len(vals)}/{MIN_DAYS_FOR_RANGE} días)",
            "level": "none",
            "p": None,
            "band": None,
        }
    dmin, dmax = rng["mean"] - 2.5 * rng["sd"], rng["mean"] + 2.5 * rng["sd"]
    span = dmax - dmin
    p = _clip((shown - dmin) / span)
    band = [_clip((rng["lo"] - dmin) / span), _clip((rng["hi"] - dmin) / span)]
    if judge:
        if rng["lo"] <= shown <= rng["hi"]:
            state, level = "en rango", "ok"
        elif shown > rng["hi"]:
            state, level = "por encima", "none"
        else:
            state, level = "por debajo", "warn" if warn_below else "none"
    else:
        prev = vals[-8:-1]
        if len(prev) >= 3:
            ref = st.mean(prev)
            change = (shown - ref) / ref if ref else 0.0
            state = "sube" if change > 0.03 else "baja" if change < -0.03 else "estable"
        else:
            state = "estable"
        level = "ok"
    # La carga solo describe dirección: sin franja «normal», que sugeriría un juicio
    return {**out, "state": state, "level": level, "p": p, "band": band if judge else None}


def _signal(label, points, fmt, tag, origin, unit_note=""):
    vals = [v for _, v in points if v is not None]
    if not vals:
        return {"label": label, "value": "—", "note": "sin datos", "tag": tag, "origin": origin}
    latest = next(v for _, v in reversed(points) if v is not None)
    note = "pocos datos"
    if len(vals) >= 3:
        # Mismo criterio que el indicador de arriba: media de 7 días junto a la de todo el periodo
        note = f"media 7 d: {fmt(st.mean(vals[-7:]))} · {len(vals)} d: {fmt(st.mean(vals))}"
    return {
        "label": label,
        "value": fmt(latest) + unit_note,
        "note": note,
        "tag": tag,
        "origin": origin,
    }


# ---------------------------------------------------------------------- estado


def estado(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    nights = _scalar(conn, "SELECT count(*) FROM daily_metrics WHERE quality <> 'excluded'")
    decision = conn.execute(
        "SELECT d, level, cause FROM decisions ORDER BY d DESC LIMIT 1"
    ).fetchone()
    if decision and nights >= NIGHTS_TARGET:
        return {
            "mode": "activo",
            "nights": nights,
            "target": NIGHTS_TARGET,
            "date": decision[0].isoformat(),
            "level": decision[1],
            "cause": decision[2],
        }
    return {"mode": "sombra", "nights": nights, "target": NIGHTS_TARGET}


# --------------------------------------------------------------------- fuentes


def _age_level(last_ok, last_error, now: datetime) -> tuple[str, int | None]:
    if last_ok is None:
        return "bad", None
    age_min = int((now - last_ok).total_seconds() // 60)
    if last_error is not None and last_error > last_ok:
        return "bad", age_min
    if age_min <= FRESH_H * 60:
        return "ok", age_min
    return ("warn" if age_min <= STALE_H * 60 else "bad"), age_min


def sources(conn: duckdb.DuckDBPyConnection, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    rows = conn.execute(
        "SELECT source, endpoint, device_id, last_ok, last_error, error "
        "FROM source_status ORDER BY source, endpoint"
    ).fetchall()
    out = []
    for source, endpoint, device_id, last_ok, last_error, error in rows:
        level, age = _age_level(last_ok, last_error, now)
        out.append(
            {
                "source": source,
                "endpoint": endpoint,
                "device": device_id,
                "level": level,
                "age_min": age,
                "last_ok": last_ok.isoformat() if last_ok else None,
                "error": error if level == "bad" else None,
            }
        )
    if not any(s["source"] == "polar" for s in out):
        n = _scalar(conn, "SELECT count(*) FROM raw_payload WHERE source='polar'")
        out.append(
            {
                "source": "polar",
                "endpoint": "—",
                "device": "global",
                "level": "none",
                "age_min": None,
                "last_ok": None,
                "error": None if n else "todavía no ha sincronizado",
            }
        )
    return out


# ------------------------------------------------------------------------ Polar Loop


def _dur_s(v: Any) -> float | None:
    """Duraciones de Polar: '26400s'."""
    if isinstance(v, str) and v.endswith("s"):
        return _num(v[:-1])
    return _num(v)


def _polar_bodies(conn: duckdb.DuckDBPyConnection, endpoint: str, limit: int) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT day, body FROM raw_payload WHERE source = 'polar' AND endpoint = ?
           QUALIFY row_number() OVER (PARTITION BY day ORDER BY fetched_at DESC, rowid DESC) = 1
           ORDER BY day DESC LIMIT ?""",
        [endpoint, limit],
    ).fetchall()
    return {d.isoformat(): _load(b) for d, b in rows}


def _steps_of(body: dict[str, Any], day_iso: str) -> int | None:
    """Pasos del día. Si Polar devuelve varios dispositivos se toma el de más pasos, no la
    suma: sumarlos contaría dos veces al mismo usuario."""
    best: float | None = None
    for d in body.get("activityDays", []):
        if d.get("date") != day_iso:
            continue
        for dev in d.get("activitiesPerDevice") or []:
            total, seen = 0.0, False
            for smp in dev.get("activitySamples") or []:
                steps = (smp.get("stepSamples") or {}).get("steps") or []
                vals = [x for x in steps if isinstance(x, int | float) and not isinstance(x, bool)]
                if vals:
                    seen, total = True, total + sum(vals)
            if seen:
                best = total if best is None else max(best, total)
    return None if best is None else int(best)


def loop_days(conn: duckdb.DuckDBPyConnection, limit: int = 60) -> list[dict[str, Any]]:
    """Un registro por día con lo que ha medido la Loop: horas dormidas, VFC y pulso nocturno de
    Nightly Recharge (respaldo de Polar hasta que la VFC propia de ARES supere el gate) y pasos."""
    sleeps = _polar_bodies(conn, "sleeps", limit)
    nr = _polar_bodies(conn, "nightly-recharge-results", limit)
    act = _polar_bodies(conn, "activity", limit)
    out = []
    for day in sorted(set(sleeps) | set(nr) | set(act))[-limit:]:
        rec: dict[str, Any] = {
            "date": day,
            "sleep_s": None,
            "nr_rmssd": None,
            "nr_hr": None,
            "steps": None,
        }
        for n in sleeps.get(day, {}).get("nightSleeps", []):
            if n.get("sleepDate") == day:
                secs = _dur_s((n.get("sleepEvaluation") or {}).get("asleepDuration"))
                rec["sleep_s"] = secs if secs and secs > 0 else None
        for r in nr.get(day, {}).get("nightlyRechargeResults", []):
            if r.get("sleepResultDate") == day:
                rmssd, rri = (
                    _num(r.get("meanNightlyRecoveryRmssd")),
                    _num(r.get("meanNightlyRecoveryRri")),
                )
                rec["nr_rmssd"] = rmssd if rmssd and rmssd > 0 else None
                rec["nr_hr"] = 60000.0 / rri if rri and rri > 0 else None
        rec["steps"] = _steps_of(act.get(day, {}), day)
        out.append(rec)
    return out


def _days_for(conn: duckdb.DuckDBPyConnection, source: str, limit: int) -> list[dict[str, Any]]:
    return loop_days(conn, limit) if source == "loop" else intervals_days(conn, limit)


def _src_status(conn: duckdb.DuckDBPyConnection, name: str, now: datetime | None) -> dict[str, Any]:
    """Estado de una fuente (la peor de sus endpoints: Polar tiene seis)."""
    rank = {"none": 0, "ok": 1, "warn": 2, "bad": 3}
    rows = [s for s in sources(conn, now) if s["source"] == name]
    if not rows:
        return {"age_min": None, "last_ok": None, "level": "none"}
    return max(rows, key=lambda s: (rank[s["level"]], s["age_min"] or 0))


def _code_version() -> str:
    """Commit del código que corre (el mismo que queda en job_runs)."""
    return jobs.git_commit()


ORIGIN_LABEL = {"INTERVALS": "intervals.icu", "POLAR": "Polar Loop"}


# ------------------------------------------------------------------------ Inicio


SPECS: dict[str, dict[str, Any]] = {
    "hrv": {
        "label": "VFC",
        "long": "Variabilidad de la frecuencia cardíaca",
        "field": "hrv",
        "scale": 1.0,
        "unit": "ms",
        "tag": "MED",
        "agg": "mean7",
        "warn": "below",
        "when": "última noche",
        "about": "Variabilidad del intervalo entre latidos que tu dispositivo envía a "
        "intervals.icu (campo hrv). En general, valores por encima de tu media se asocian a "
        "mejor recuperación y por debajo a más carga o cansancio; pero lo relevante es la "
        "tendencia frente a tu propio rango, no el número aislado.",
    },
    "rhr": {
        "label": "Pulso en reposo",
        "long": "Frecuencia cardíaca en reposo",
        "field": "restingHR",
        "scale": 1.0,
        "unit": "lpm",
        "tag": "MED",
        "agg": "mean7",
        "warn": "above",
        "when": "último día",
        "about": "Pulso en reposo que registra tu dispositivo. Una subida sostenida sobre tu "
        "media puede acompañar a fatiga, poco sueño o enfermedad; un día suelto no significa nada.",
    },
    "sleep": {
        "label": "Sueño",
        "long": "Horas dormidas",
        "field": "sleepSecs",
        "scale": 1 / 3600,
        "unit": "h",
        "tag": "MED",
        "agg": "last",
        "warn": "below",
        "when": "última noche",
        "about": "Horas dormidas que registra tu dispositivo. ARES mira la duración frente a tu "
        "media y, cuando llegue la Loop, también la regularidad del horario.",
    },
    "sleep_hr": {
        "label": "Pulso durante el sueño",
        "long": "Frecuencia cardíaca media mientras duermes",
        "field": "avgSleepingHR",
        "scale": 1.0,
        "unit": "lpm",
        "tag": "MED",
        "agg": "mean7",
        "warn": "above",
        "when": "última noche",
        "about": "Pulso medio durante el sueño. Se mueve en paralelo al pulso en reposo y sirve "
        "para contrastarlo.",
    },
    "ctl": {
        "label": "Forma (CTL)",
        "long": "Carga crónica de entrenamiento",
        "field": "ctl",
        "scale": 1.0,
        "unit": "",
        "tag": "CALC",
        "agg": "last",
        "warn": None,
        "when": "último día",
        "about": "Modelo de intervals.icu (de tipo Banister/Coggan): promedio exponencial de la "
        "carga diaria de entrenamiento. Por defecto la forma (CTL) usa una constante de 42 días "
        "y la fatiga (ATL) de 7; se pueden cambiar en intervals.icu. La carga de cada sesión es "
        "una estimación de intervals.icu (con FC, potencia o ritmo, según lo que traigan tus "
        "actividades), no una medida fisiológica.",
    },
    "atl": {
        "label": "Fatiga (ATL)",
        "long": "Carga aguda de entrenamiento",
        "field": "atl",
        "scale": 1.0,
        "unit": "",
        "tag": "CALC",
        "agg": "last",
        "warn": None,
        "when": "último día",
        "about": "Mismo modelo que la forma, con una constante corta (por defecto 7 días): sube "
        "y baja rápido con la carga reciente. Es una estimación de intervals.icu.",
    },
}
for _sp in SPECS.values():  # las señales de intervals.icu, con su origen explícito
    _sp.setdefault("source", "intervals")
    _sp.setdefault("origin", "INTERVALS")
SPECS["sleep"]["fmt"] = "hm"
SPECS.update(
    {
        "loop_sleep": {
            "label": "Sueño",
            "long": "Horas dormidas (Polar Loop)",
            "field": "sleep_s",
            "scale": 1 / 3600,
            "unit": "h",
            "tag": "MED",
            "agg": "last",
            "warn": "below",
            "when": "última noche",
            "fmt": "hm",
            "source": "loop",
            "origin": "POLAR",
            "about": "Tiempo dormido que mide la Loop, sin contar los despertares. ARES lo compara "
            "con tu propia media y, cuando haya más noches, también la regularidad del horario.",
        },
        "loop_hrv": {
            "label": "VFC",
            "long": "Variabilidad de la frecuencia cardíaca (Nightly Recharge)",
            "field": "nr_rmssd",
            "scale": 1.0,
            "unit": "ms",
            "tag": "CALC",
            "agg": "mean7",
            "warn": "below",
            "when": "última noche",
            "source": "loop",
            "origin": "POLAR",
            "about": "rMSSD medio de la noche que calcula Polar (Nightly Recharge) con los "
            "intervalos entre latidos de la Loop. Es el respaldo hasta que la VFC propia de ARES "
            "supere el gate contra la H10. Lo relevante es tu tendencia frente a tu propio rango.",
        },
        "loop_hr": {
            "label": "Pulso nocturno",
            "long": "Frecuencia cardíaca media en las primeras horas de sueño",
            "field": "nr_hr",
            "scale": 1.0,
            "unit": "lpm",
            "tag": "CALC",
            "agg": "mean7",
            "warn": "above",
            "when": "última noche",
            "source": "loop",
            "origin": "POLAR",
            "about": "Se deduce del intervalo entre latidos medio de la recuperación nocturna de "
            "Nightly Recharge. Se mueve en paralelo al pulso en reposo. Una subida sostenida sobre "
            "tu media puede acompañar a fatiga, poco sueño o enfermedad.",
        },
    }
)
PERIODS = (7, 28, 90, 365)
SIGNAL_ORDER_LOOP = ("loop_hrv", "loop_hr", "loop_sleep", "ctl")
SIGNAL_ORDER = ("hrv", "rhr", "sleep", "sleep_hr", "ctl")
DIAL_SIGNAL = {"noche": "sleep", "nervioso": "hrv", "carga": "ctl"}


def _sg(x: float, digits: int = 0) -> str:
    if round(x, digits) == 0:
        return "±0"
    return f"{x:+.{digits}f}".replace("-", "−")


def _spec_points(days: list[dict[str, Any]], key: str):
    sp = SPECS[key]
    return [
        (d["date"], None if d[sp["field"]] is None else d[sp["field"]] * sp["scale"]) for d in days
    ]


def _val(key: str, v: float) -> str:
    return fmt_hm(v) if SPECS[key].get("fmt") == "hm" else f"{v:.0f}"


def _val_u(key: str, v: float) -> str:
    unit = SPECS[key]["unit"]
    return f"{_val(key, v)} {unit}" if unit else _val(key, v)


def _signal_row(key: str, days: list[dict[str, Any]]) -> dict[str, Any]:
    sp = SPECS[key]
    vals = [v for _, v in _spec_points(days, key) if v is not None]
    row = {
        "key": key,
        "label": f"{sp['label']} · {sp['when']}",
        "tag": sp["tag"],
        "origin": sp["origin"],
        "unit": sp["unit"],
        "spark": [round(v, 2) for v in vals[-14:]],
    }
    if not vals:
        return {**row, "value": "—", "note": "sin datos"}
    note = "pocos datos"
    if len(vals) >= 3:
        m7, mall = _val(key, st.mean(vals[-7:])), _val(key, st.mean(vals))
        note = f"media 7 d: {m7} · {len(vals)} d: {mall}"
    return {**row, "value": _val_u(key, vals[-1]), "note": note}


def home(
    conn: duckdb.DuckDBPyConnection, now: datetime | None = None, source: str = "intervals"
) -> dict[str, Any]:
    """`source="loop"`: sueño, VFC, pulso nocturno y pasos salen de la Loop (que llevas siempre).
    La carga (CTL) sigue siendo de intervals.icu: sale de los entrenos, no del reloj puesto 24 h."""
    loop = source == "loop"
    days = intervals_days(conn)
    wdays = loop_days(conn) if loop else days
    origin = "POLAR" if loop else "INTERVALS"
    hours = _points(wdays, "sleep_s" if loop else "sleepSecs", 1 / 3600)
    hrv = _points(wdays, "nr_rmssd" if loop else "hrv")
    ctl = _points(days, "ctl")
    note = (
        "media 7 d de Nightly Recharge (Polar), no es la VFC propia de ARES"
        if loop
        else "media 7 d de intervals.icu, no es la VFC de ARES: esa llegará con la Loop"
    )
    dials = [
        make_dial("noche", "NOCHE", hours, fmt_hm, "MED", origin, "horas dormidas"),
        make_dial(
            "nervioso",
            "SIST. NERVIOSO",
            hrv,
            lambda v: f"{v:.0f} ms",
            "CALC" if loop else "MED",
            origin,
            note,
            agg="mean7",
        ),
        make_dial(
            "carga",
            "CARGA",
            ctl,
            lambda v: f"{v:.0f}",
            "CALC",
            "INTERVALS",
            "forma (CTL) de intervals.icu",
            judge=False,
        ),
    ]
    dial_signal = {
        "noche": "loop_sleep" if loop else "sleep",
        "nervioso": "loop_hrv" if loop else "hrv",
        "carga": "ctl",
    }
    for d in dials:
        d["signal"] = dial_signal[d["key"]]
        d["trend"] = None
    nv = [v for _, v in hours if v is not None]
    if len(nv) >= 8:  # última noche frente a las 7 anteriores
        dials[0]["trend"] = f"{_sg((nv[-1] - st.mean(nv[-8:-1])) * 60)} min vs 7 d"
    hv = [v for _, v in hrv if v is not None]
    rng = personal_range(hv)
    if rng:  # media de 7 días frente a tu media (el indicador ya es la media de 7 días)
        dials[1]["trend"] = f"{_sg(st.mean(hv[-7:]) - rng['mean'])} ms vs tu media"
    cv = [v for _, v in ctl if v is not None]
    if len(cv) >= 8 and cv[-8] > 0:  # forma hoy frente a hace 7 días
        dials[2]["trend"] = f"{_sg((cv[-1] / cv[-8] - 1) * 100)} % en 7 d"
    steps_pt = next(
        ((d["date"], d["steps"]) for d in reversed(wdays) if d["steps"] is not None), None
    )
    keys = SIGNAL_ORDER_LOOP if loop else SIGNAL_ORDER
    return {
        "estado": estado(conn),
        "dials": dials,
        "signals": [_signal_row(k, wdays if SPECS[k]["source"] == "loop" else days) for k in keys],
        "steps": None if steps_pt is None else int(steps_pt[1]),
        "steps_day": None if steps_pt is None else steps_pt[0],
        "steps_source": "Polar Loop" if loop else "intervals.icu",
        "source": source,
        "sources": sources(conn, now),
        "days": len(wdays),
        "last_day": wdays[-1]["date"] if wdays else None,
    }


# ----------------------------------------------------------------------- Detalle


def _judge(shown: float, rng: dict[str, float], warn: str | None) -> tuple[str, str]:
    """Estado de un valor frente a la franja personal. Solo el lado peligroso avisa."""
    if rng["lo"] <= shown <= rng["hi"]:
        return "en rango", "ok"
    side = "above" if shown > rng["hi"] else "below"
    return f"por {'encima' if side == 'above' else 'debajo'}", "warn" if side == warn else "none"


def _interpret(sp, key, state, level, shown_s, lo_s, hi_s, n, agg) -> dict[str, str]:
    label = sp["label"]
    if lo_s is None:
        return {
            "title": "Aún no hay rango habitual",
            "text": f"Hacen falta {MIN_DAYS_FOR_RANGE} días para calcularlo y hay {n}.",
        }
    if sp["warn"] is None:
        return {
            "title": f"Tendencia: {state}",
            "text": "Este modelo describe carga acumulada. ARES lo muestra tal cual y no lo "
            "interpreta como bueno o malo.",
        }
    span = "La última noche" if agg == "last" else "La media de los últimos 7 días"
    if state == "en rango":
        return {
            "title": f"{label} dentro de tu rango habitual",
            "text": f"{span} está dentro de tu rango. Úsala junto con el sueño y la carga; en "
            "modo sombra ARES no la convierte en recomendación.",
        }
    return {
        "title": f"{label} {state} de tu rango habitual",
        "text": f"{span} vale {shown_s} frente a un rango de {lo_s} a {hi_s}. Un día suelto no "
        "significa nada por sí solo; conviene mirar si se mantiene varios días. ARES no actúa "
        "sobre esto hasta completar la línea base.",
    }


def signal_detail(
    conn: duckdb.DuckDBPyConnection, key: str, days: int = 28, now: datetime | None = None
) -> dict[str, Any]:
    sp = SPECS[key]
    all_days = _days_for(conn, sp["source"], 400)
    pts = [(d, v) for d, v in _spec_points(all_days, key) if v is not None]
    src = _src_status(conn, "polar" if sp["origin"] == "POLAR" else "intervals", now)
    if sp["origin"] == "POLAR":
        nature = (
            "MED · medido por la Loop"
            if sp["tag"] == "MED"
            else "CALC · calculado por Polar (Nightly Recharge) con los intervalos de la Loop"
        )
    else:
        nature = (
            "MED · medido por el dispositivo; intervals.icu solo lo transmite"
            if sp["tag"] == "MED"
            else "CALC · calculado por intervals.icu a partir de la carga de tus sesiones"
        )
    base = {
        "key": key,
        "label": sp["label"],
        "long": sp["long"],
        "unit": sp["unit"],
        "tag": sp["tag"],
        "origin": sp["origin"],
        "source_label": ORIGIN_LABEL[sp["origin"]],
        "nature": nature,
        "about": sp["about"],
        "periods": list(PERIODS),
        "days": days,
        "updated_min": src["age_min"],
        "updated_level": src["level"],
    }
    if not pts:
        return {**base, "empty": True}
    last_date = date.fromisoformat(pts[-1][0])
    first_date = date.fromisoformat(pts[0][0])
    available = (last_date - first_date).days + 1
    cutoff = last_date - timedelta(days=days - 1)
    window = [(d, v) for d, v in pts if date.fromisoformat(d) >= cutoff]
    ref = [v for d, v in pts if date.fromisoformat(d) >= last_date - timedelta(days=59)]
    rng = personal_range(ref)
    vals = [v for _, v in pts]
    mean7 = st.mean(vals[-7:])
    shown = mean7 if sp["agg"] == "mean7" else vals[-1]
    wv = [v for _, v in window]
    span_days = (last_date - max(cutoff, first_date)).days + 1
    fmt = lambda v: _val(key, v)  # noqa: E731
    if rng is None:
        state, level = f"sin rango ({len(ref)}/{MIN_DAYS_FOR_RANGE} días)", "none"
    elif sp["warn"] is None:
        prev = vals[-8:-1]
        ref_mean = st.mean(prev) if len(prev) >= 3 else vals[-1]
        change = (vals[-1] - ref_mean) / ref_mean if ref_mean else 0.0
        state = "sube" if change > 0.03 else "baja" if change < -0.03 else "estable"
        level = "ok"
    else:
        state, level = _judge(shown, rng, sp["warn"])
    lo_s = fmt(rng["lo"]) if rng else None
    hi_s = fmt(rng["hi"]) if rng else None
    return {
        **base,
        "empty": False,
        "kind": "trend" if sp["warn"] is None else "band",
        "value": _val_u(key, vals[-1]),
        "date": pts[-1][0],
        "agg": sp["agg"],
        "shown": _val_u(key, shown),
        "state": state,
        "level": level,
        "mean7": _val_u(key, mean7),
        "mean_ref": _val_u(key, rng["mean"]) if rng else None,
        "n_ref": len(ref),
        "range": {"lo": rng["lo"], "hi": rng["hi"], "lo_s": lo_s, "hi_s": hi_s} if rng else None,
        "series": [{"date": d, "v": round(v, 3)} for d, v in window],
        "stats": {
            "min": _val_u(key, min(wv)),
            "mean": _val_u(key, st.mean(wv)),
            "max": _val_u(key, max(wv)),
            "last": _val_u(key, wv[-1]),
        },
        "coverage": round(100 * len(window) / span_days),
        "available_days": available,
        "partial": available < days,
        "interpretation": _interpret(
            sp, key, state, level, _val_u(key, shown), lo_s, hi_s, len(ref), sp["agg"]
        ),
    }


# ---------------------------------------------------------------------- Progreso


def _tredict_latest(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT body FROM raw_payload WHERE source='tredict' AND endpoint='activity'
           ORDER BY fetched_at DESC LIMIT 600"""
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for (body,) in rows:
        item = _load(body)
        aid = str(item.get("id", ""))
        if aid and aid not in latest:
            latest[aid] = item
    return sorted(latest.values(), key=lambda a: str(a.get("date", "")), reverse=True)


def tredict_activities(conn: duckdb.DuckDBPyConnection, limit: int = 12) -> list[dict[str, Any]]:
    return [
        {"date": str(a.get("date", ""))[:10], "sport": a.get("sportType") or "—"}
        for a in _tredict_latest(conn)[:limit]
    ]


def weekly_sessions(
    conn: duckdb.DuckDBPyConnection, weeks: int = 8, today: date | None = None
) -> list[dict[str, Any]]:
    """Sesiones por semana (lunes a domingo) según la lista de Tredict."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    starts = [monday - timedelta(weeks=k) for k in range(weeks - 1, -1, -1)]
    counts = {w: [0, 0] for w in starts}
    for a in _tredict_latest(conn):
        try:
            d = date.fromisoformat(str(a.get("date", ""))[:10])
        except ValueError:
            continue
        w = d - timedelta(days=d.weekday())
        if w in counts:
            counts[w][0] += 1
            counts[w][1] += 1 if a.get("sportType") == "running" else 0
    return [{"week": w.isoformat(), "sessions": c[0], "running": c[1]} for w, c in counts.items()]


def progreso(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> dict[str, Any]:
    days = intervals_days(conn, limit=400)
    last = days[-1] if days else None
    stats = None
    if last and last["ctl"] is not None and last["atl"] is not None:
        stats = {
            "ctl": round(last["ctl"], 1),
            "atl": round(last["atl"], 1),
            "form": round(last["ctl"] - last["atl"], 1),
            "ramp": None if last["rampRate"] is None else round(last["rampRate"], 1),
            "date": last["date"],
        }
    return {
        "ctl": [{"date": d["date"], "v": d["ctl"]} for d in days if d["ctl"] is not None],
        "atl": [{"date": d["date"], "v": d["atl"]} for d in days if d["atl"] is not None],
        "stats": stats,
        "weeks": weekly_sessions(conn, today=today),
        "activities": tredict_activities(conn),
        "n_activities": _scalar(
            conn,
            "SELECT count(*) FROM raw_payload WHERE source='tredict' AND endpoint='activity'",
        ),
    }


# --------------------------------------------------------------------------- Lab


def lab(conn: duckdb.DuckDBPyConnection, settings, now: datetime | None = None) -> dict[str, Any]:
    raw = conn.execute(
        "SELECT source, endpoint, count(*), min(day), max(day) FROM raw_payload "
        "GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    runs = conn.execute(
        "SELECT job, status, started, git_commit FROM job_runs ORDER BY started DESC LIMIT 8"
    ).fetchall()
    version = _scalar(conn, "SELECT max(version) FROM schema_version")
    return {
        "sources": sources(conn, now),
        "raw": [
            {"source": s, "endpoint": e, "rows": n, "from": a.isoformat(), "to": b.isoformat()}
            for s, e, n, a, b in raw
        ],
        "runs": [
            {"job": j, "status": s, "started": t.astimezone(UTC).isoformat(), "commit": c}
            for j, s, t, c in runs
        ],
        "gate": {
            "level": "sin evaluar",
            "n_h10": 0,
            "criteria": "PROVISIONAL con 5 noches H10 · VALIDATED con 8–10",
        },
        "versions": {
            "schema": version,
            "rules": settings.rules_version,
            "filter": settings.filter_version,
            "code": _code_version(),
        },
        "generated": (now or datetime.now(UTC)).isoformat(),
    }
