"""Lo que la app enseña, calculado solo a partir de la base (nunca escribe).

Principio de la UX v1: nada de puntuaciones inventadas. Cada valor lleva su etiqueta
(MED/CALC/EST/EXP) y su origen, y lo que aún no existe se dice tal cual («sin datos»,
«modo sombra»). El dispositivo de origen de intervals.icu se declara en la
configuración (COROS por defecto) y no se valida a través del payload wellness.
El motor nocturno utiliza WHOOP directo. Las medias de ambos se muestran con
procedencia explícita y no alteran la capa bruta ni activan decisiones.
"""

from __future__ import annotations

import json
import statistics as st
from datetime import UTC, date, datetime, timedelta
from typing import Any

import duckdb

from .. import jobs
from . import fusion

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
           QUALIFY row_number() OVER (PARTITION BY day ORDER BY fetched_at DESC) = 1
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
                "readiness": _num(rec.get("readiness")),
                "respiration": _num(rec.get("respiration")),
                "spO2": _num(rec.get("spO2")),
                "sleepScore": _num(rec.get("sleepScore")),
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
        "FROM source_status WHERE source IN ('whoop', 'intervals', 'tredict') "
        "ORDER BY source, endpoint"
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
    return out


def _src_status(conn: duckdb.DuckDBPyConnection, name: str, now: datetime | None) -> dict[str, Any]:
    """Estado de una fuente: la peor de sus endpoints."""
    rank = {"none": 0, "ok": 1, "warn": 2, "bad": 3}
    rows = [s for s in sources(conn, now) if s["source"] == name]
    if not rows:
        return {"age_min": None, "last_ok": None, "level": "none"}
    return max(rows, key=lambda s: (rank[s["level"]], s["age_min"] or 0))


def _code_version() -> str:
    """Commit del código que corre (el mismo que queda en job_runs)."""
    return jobs.git_commit()


ORIGIN_LABEL = {"INTERVALS": "intervals.icu"}
VIA = "vía INTERVALS"  # lo que mide la pulsera y llega por intervals.icu


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
        "media.",
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
for _k in ("hrv", "rhr", "sleep", "sleep_hr"):
    SPECS[_k]["wellness"] = True  # lo mide la pulsera conectada a intervals.icu, sea cual sea
SPECS.update(
    {
        "recovery": {
            "label": "Recovery",
            "long": "Recuperación (puntuación del dispositivo)",
            "field": "readiness",
            "scale": 1.0,
            "unit": "%",
            "tag": "CALC",
            "agg": "last",
            "warn": "below",
            "when": "hoy",
            "source": "intervals",
            "origin": "INTERVALS",
            "wellness": True,
            "about": "Puntuación de recuperación que calcula tu dispositivo con sus propios "
            "criterios y que intervals.icu transmite (campo readiness). ARES la guarda tal cual y "
            "la compara con TU rango, pero no conoce la fórmula: es un modelo externo, no una "
            "medida.",
        },
        "spo2": {
            "label": "SpO₂",
            "long": "Saturación de oxígeno nocturna",
            "field": "spO2",
            "scale": 1.0,
            "unit": "%",
            "tag": "MED",
            "agg": "mean7",
            "warn": "below",
            "when": "última noche",
            "source": "intervals",
            "origin": "INTERVALS",
            "wellness": True,
            "about": "Saturación media de oxígeno durante el sueño según el dispositivo. Lo "
            "habitual es que sea muy estable entre 94 y 98: importa una bajada sostenida frente a "
            "tu media, no un día suelto. No es una prueba médica.",
        },
        "resp": {
            "label": "Respiración",
            "long": "Frecuencia respiratoria nocturna",
            "field": "respiration",
            "scale": 1.0,
            "unit": "rpm",
            "tag": "MED",
            "agg": "mean7",
            "warn": "above",
            "when": "última noche",
            "source": "intervals",
            "origin": "INTERVALS",
            "wellness": True,
            "about": "Respiraciones por minuto durante el sueño. En cada persona es muy estable: "
            "una subida sostenida sobre tu media puede acompañar a enfermedad, fatiga o estrés.",
        },
        "sleep_score": {
            "label": "Calidad de sueño",
            "long": "Puntuación de sueño (del dispositivo)",
            "field": "sleepScore",
            "scale": 1.0,
            "unit": "",
            "tag": "CALC",
            "agg": "last",
            "warn": "below",
            "when": "última noche",
            "source": "intervals",
            "origin": "INTERVALS",
            "wellness": True,
            "about": "Puntuación de sueño que calcula tu dispositivo (duración, eficiencia, "
            "constancia...) y que intervals.icu transmite (campo sleepScore). Es un modelo "
            "externo: ARES la compara con tu rango, pero no conoce la fórmula.",
        },
    }
)
PERIODS = (7, 28, 90, 365)
SIGNAL_ORDER = ("hrv", "rhr", "sleep", "sleep_hr", "ctl")
SIGNAL_ORDER_WELLNESS = ("recovery", "hrv", "rhr", "sleep", "spo2", "resp", "ctl")
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


def _origin(sp: dict[str, Any], device: str | None) -> str:
    """Origen que se muestra: lo que mide la pulsera y transmite intervals.icu lleva
    «<PULSERA> vía INTERVALS»; lo demás, el suyo."""
    return f"{device.upper()} {VIA}" if device and sp.get("wellness") else sp["origin"]


def _signal_row(key: str, days: list[dict[str, Any]], device: str | None = None) -> dict[str, Any]:
    sp = SPECS[key]
    vals = [v for _, v in _spec_points(days, key) if v is not None]
    row = {
        "key": key,
        "label": f"{sp['label']} · {sp['when']}",
        "tag": sp["tag"],
        "origin": _origin(sp, device),
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
    conn: duckdb.DuckDBPyConnection,
    now: datetime | None = None,
    device: str | None = None,
    device_id: str | None = None,
) -> dict[str, Any]:
    """Inicio con el bienestar de intervals.icu. Con `device` (la pulsera conectada allí), lo
    que ella mide se etiqueta «<PULSERA> vía INTERVALS». La carga (CTL) es de intervals.icu."""
    days = intervals_days(conn)
    fused = (
        fusion.combine(
            conn, device_id, intervals_days(conn, limit=120), source_device=device or "Intervals"
        )
        if device_id else None
    )
    origin = f"{device.upper()} {VIA}" if device else "INTERVALS"
    hours = _points(days, "sleepSecs", 1 / 3600)
    hrv = _points(days, "hrv")
    ctl = _points(days, "ctl")
    note = f"media 7 d de {device or 'intervals.icu'}, no es una VFC calculada por ARES"
    dials = [
        make_dial("noche", "NOCHE", hours, fmt_hm, "MED", origin, "horas dormidas"),
        make_dial(
            "nervioso",
            "SIST. NERVIOSO",
            hrv,
            lambda v: f"{v:.0f} ms",
            "MED",
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
    # Los indicadores superiores priorizan pares WHOOP + COROS de la última noche.
    # Una serie desactualizada no sustituye silenciosamente el dato más reciente.
    if fused and fused["latest"]:
        latest = fused["latest"]
        series = fused["series"]
        combined_origin = f"ARES · WHOOP + {device.upper() if device else 'INTERVALS'}"
        if latest["metrics"]["sleep_min"]["paired"]:
            hours = [(r["date"], None if r["sleep_min"] is None else r["sleep_min"] / 60)
                     for r in series]
            dials[0] = make_dial(
                "noche", "NOCHE", hours, fmt_hm, "CALC", combined_origin,
                "media 50/50 de sueño efectivo, misma fecha; sin uso clínico"
            )
        if latest["metrics"]["hrv"]["paired"]:
            hrv = [(r["date"], r["hrv"]) for r in series]
            dials[1] = make_dial(
                "nervioso", "SIST. NERVIOSO", hrv,
                lambda v: f"{v:.0f} ms", "EXP", combined_origin,
                "media 50/50 rMSSD; métodos de medición aún no validados", agg="mean7"
            )
    for d in dials:
        d["signal"] = DIAL_SIGNAL[d["key"]]
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
        ((d["date"], d["steps"]) for d in reversed(days) if d["steps"] is not None), None
    )
    keys = SIGNAL_ORDER_WELLNESS if device else SIGNAL_ORDER
    return {
        "estado": estado(conn),
        "whoop": whoop_night_summary(conn, device_id) if device_id else None,
        "fusion": fused,
        "dials": dials,
        "signals": [_signal_row(k, days, device) for k in keys],
        "steps": None if steps_pt is None else int(steps_pt[1]),
        "steps_day": None if steps_pt is None else steps_pt[0],
        "steps_source": "intervals.icu",
        "sources": sources(conn, now),
        "days": len(days),
        "last_day": days[-1]["date"] if days else None,
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
    conn: duckdb.DuckDBPyConnection,
    key: str,
    days: int = 28,
    now: datetime | None = None,
    device: str | None = None,
) -> dict[str, Any]:
    sp = SPECS[key]
    all_days = intervals_days(conn, 400)
    pts = [(d, v) for d, v in _spec_points(all_days, key) if v is not None]
    src = _src_status(conn, "intervals", now)
    dev = device.upper() if device and sp.get("wellness") else None
    if dev:
        nature = (
            f"MED · medido por {dev}; intervals.icu solo lo transmite"
            if sp["tag"] == "MED"
            else f"CALC · calculado por {dev} y transmitido por intervals.icu"
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
        "origin": f"{dev} {VIA}" if dev else sp["origin"],
        "source_label": f"{dev} {VIA}" if dev else ORIGIN_LABEL[sp["origin"]],
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


# ------------------------------------------------------------------ WHOOP directo


def whoop_night_summary(
    conn: duckdb.DuckDBPyConnection, device_id: str, limit: int = 90
) -> dict[str, Any]:
    """Resumen estrictamente medido por WHOOP, sin mezclar wellness de Intervals.

    El último día se enseña aunque no tenga una puntuación válida; no se sustituye
    silenciosamente por una noche anterior. La calidad procede del motor ARES.
    Solo lee daily_metrics, nunca modifica la base ni fuerza sincronizaciones.
    """
    rows = conn.execute(
        """SELECT local_sleep_date, sleep_min, rmssd_ms, rhr, resp_rate, spo2,
                  skin_temp, provider_recovery, score_state, calibrating,
                  quality, night_check
           FROM daily_metrics WHERE device_id = ?
           ORDER BY local_sleep_date DESC LIMIT ?""",
        [device_id, limit],
    ).fetchall()
    qualities = {"high": 0, "fair": 0, "excluded": 0}
    for row in rows:
        q = row[10]
        qualities[q if q in qualities else "excluded"] += 1
    if not rows:
        return {
            "source": "WHOOP directo",
            "device_id": device_id,
            "nights": 0,
            "valid_nights": 0,
            "qualities": qualities,
            "latest": None,
        }
    last = rows[0]
    return {
        "source": "WHOOP directo",
        "device_id": device_id,
        "nights": len(rows),
        "valid_nights": qualities["high"] + qualities["fair"],
        "qualities": qualities,
        "latest": {
            "date": last[0].isoformat(),
            "sleep_min": last[1],
            "rmssd_ms": last[2],
            "rhr": last[3],
            "resp_rate": last[4],
            "spo2": last[5],
            "skin_temp": last[6],
            "provider_recovery": last[7],
            "score_state": last[8],
            "calibrating": last[9],
            "quality": last[10],
            "night_check": last[11],
        },
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
        "WHERE source IN ('whoop', 'intervals', 'tredict') "
        "GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    runs = conn.execute(
        "SELECT job, status, started, git_commit FROM job_runs "
        "WHERE lower(job) NOT LIKE '%polar%' ORDER BY started DESC LIMIT 8"
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
            "algo": settings.algo_version,
            "code": _code_version(),
        },
        "generated": (now or datetime.now(UTC)).isoformat(),
    }
