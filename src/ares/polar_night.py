"""Análisis de una noche real de la Loop a partir de las respuestas que guardó la sonda.

Prototipo del pipeline del plan (bruto → marcas de calidad → serie corregida → rMSSD) sobre
datos reales, sin escribir en la base. Saca tres cosas que el diseño daba por supuestas:
cómo se alinean los PPI con el sueño, cuánto elimina cada regla del filtro v0.3 y qué tal
coincide el rMSSD de ARES con el de Nightly Recharge de Polar. Todo agregado: ningún valor
de latido suelto.
"""

from __future__ import annotations

import json
import math
import statistics as st
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SEG_MS = 300_000  # segmentos de 5 min, como Nightly Recharge
MAX_ERR_MS, PP_MIN, PP_MAX, DELTA = 20, 300, 2000, 0.20  # filtro v0.3 del plan
WINDOW_OFFSET_MS, WINDOW_LEN_MS = 30 * 60_000, 4 * 3_600_000
MIN_DIFFS = 30  # diferencias válidas mínimas para dar un rMSSD de segmento
RULES = ("movimiento", "contacto", "error", "rango", "salto")
VARIANTS: dict[str, frozenset[str]] = {
    "filtro v0.3 (todas las reglas)": frozenset(),
    "sin la regla de movimiento": frozenset({"movimiento"}),
    "sin la regla de error": frozenset({"error"}),
    "sin la regla de salto": frozenset({"salto"}),
    "solo contacto y rango": frozenset({"movimiento", "error", "salto"}),
}


class NightError(RuntimeError):
    """Falta algún fichero de la sonda; el mensaje dice cuál y qué hacer."""


@dataclass(frozen=True)
class Beat:
    t: int  # ms desde 1970 en UTC
    pp: int  # intervalo, ms
    err: int  # error estimado, ms
    contact: bool
    move: bool


# ------------------------------------------------------------------ lectura


def day_start_ms(day: date, tz: ZoneInfo) -> int:
    """Medianoche local del día en ms UTC. Los PPI de Polar cuentan desde ahí, sin zona."""
    return int(datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(UTC).timestamp() * 1000)


def beats_from_doc(doc: dict[str, Any], day: date, tz: ZoneInfo) -> list[Beat]:
    base = day_start_ms(day, tz)
    out: list[Beat] = []
    for entry in doc.get("dailyPpiSamples", []):
        if entry.get("date") != day.isoformat():
            continue
        devs = entry.get("ppiSamplesPerDevice") or []
        if not devs:
            continue
        best = max(devs, key=lambda d: len(d.get("ppiSamples") or []))
        for s in best.get("ppiSamples") or []:
            try:
                out.append(
                    Beat(
                        base + int(s["offsetMillis"]),
                        int(s["ppInterval"]),
                        int(s.get("errorEstimateMillis", 0)),
                        bool(s.get("skinContact", True)),
                        bool(s.get("movement", False)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda b: b.t)
    return out


def _dirs(root: Path) -> list[Path]:
    return sorted((p for p in root.iterdir() if p.is_dir()), reverse=True) if root.exists() else []


def find_doc(root: Path, filename: str, match) -> dict[str, Any] | None:
    for d in _dirs(root):
        f = d / filename
        if not f.exists():
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(doc, dict) and match(doc):
            return doc
    return None


def _has_ppi(day: date):
    return lambda doc: any(
        e.get("date") == day.isoformat()
        and any(d.get("ppiSamples") for d in e.get("ppiSamplesPerDevice") or [])
        for e in doc.get("dailyPpiSamples", [])
    )


def parse_sleep(doc: dict[str, Any], sleep_date: date) -> dict[str, Any] | None:
    for n in doc.get("nightSleeps", []):
        if n.get("sleepDate") != sleep_date.isoformat():
            continue
        h = (n.get("sleepResult") or {}).get("hypnogram") or {}
        if not h.get("sleepStart") or not h.get("sleepEnd"):
            continue
        start, end = datetime.fromisoformat(h["sleepStart"]), datetime.fromisoformat(h["sleepEnd"])
        return {
            "start": start.astimezone(UTC),
            "end": end.astimezone(UTC),
            "zone": start.utcoffset(),
            "battery": h.get("batteryRanOut"),
        }
    return None


# ------------------------------------------------------------------- filtro


def flags(beats: list[Beat]) -> list[frozenset[str]]:
    out: list[frozenset[str]] = []
    prev: Beat | None = None
    for b in beats:
        r: set[str] = set()
        if b.move:
            r.add("movimiento")
        if not b.contact:
            r.add("contacto")
        if b.err > MAX_ERR_MS:
            r.add("error")
        if not PP_MIN <= b.pp <= PP_MAX:
            r.add("rango")
        if prev is not None and abs(b.pp - prev.pp) > DELTA * prev.pp:
            r.add("salto")
        out.append(frozenset(r))
        prev = b
    return out


def detect_mode(beats: list[Beat]) -> tuple[str, float | None]:
    """¿El offset marca el final de cada intervalo, su inicio o ninguna de las dos cosas?
    Se decide con los propios datos: el hueco entre latidos debe igualar su intervalo."""
    ends: list[float] = []
    starts: list[float] = []
    for a, b in zip(beats, beats[1:], strict=False):
        gap = b.t - a.t
        if 0 < gap < 3000:
            ends.append(abs(gap - b.pp))
            starts.append(abs(gap - a.pp))
    if len(ends) < 50:
        return "hueco", None
    me, ms = st.median(ends), st.median(starts)
    if min(me, ms) < 60:
        return ("fin" if me <= ms else "inicio"), min(me, ms)
    return "hueco", min(me, ms)


def consecutive(a: Beat, b: Beat, mode: str) -> bool:
    gap = b.t - a.t
    if mode == "fin":
        return abs(gap - b.pp) <= 60
    if mode == "inicio":
        return abs(gap - a.pp) <= 60
    return 0 < gap < 2000


def valid_diffs(
    beats: list[Beat], fl: list[frozenset[str]], ignore: frozenset[str], mode: str
) -> list[tuple[int, int]]:
    """(instante del segundo latido, diferencia sucesiva) de cada par consecutivo válido."""
    ok = [not (f - ignore) for f in fl]
    return [
        (beats[i].t, beats[i].pp - beats[i - 1].pp)
        for i in range(1, len(beats))
        if ok[i] and ok[i - 1] and consecutive(beats[i - 1], beats[i], mode)
    ]


def seg_rmssd(
    diffs: list[tuple[int, int]],
    t0: float,
    n_seg: int,
    seg_ms: int = SEG_MS,
    min_diffs: int = MIN_DIFFS,
) -> list[float | None]:
    bins: list[list[int]] = [[] for _ in range(n_seg)]
    for t, d in diffs:
        k = int((t - t0) // seg_ms)
        if 0 <= k < n_seg:
            bins[k].append(d)
    return [
        math.sqrt(sum(x * x for x in b) / len(b)) if len(b) >= min_diffs else None for b in bins
    ]


def _median_ms(segs: list[float | None]) -> float | None:
    vals = [v for v in segs if v is not None]
    return st.median(vals) if vals else None


# ------------------------------------------------------------ Nightly Recharge


def _stats(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    n = len(pairs)
    if n < 3:
        return {"n": n}
    a, b = [p[0] for p in pairs], [p[1] for p in pairs]
    diff = [x - y for x, y in pairs]
    r = None
    if st.pstdev(a) > 0 and st.pstdev(b) > 0:
        r = st.correlation(a, b)
    return {"n": n, "bias_ln": st.mean(diff), "mae_ln": st.mean(abs(d) for d in diff), "r": r}


def nr_comparison(
    nr_doc: dict[str, Any],
    sleep_date: date,
    diffs_by_variant: dict[str, list[tuple[int, int]]],
    tz: ZoneInfo,
) -> dict[str, Any] | None:
    rec = next(
        (
            r
            for r in nr_doc.get("nightlyRechargeResults", [])
            if r.get("sleepResultDate") == sleep_date.isoformat() and r.get("hrvSamples")
        ),
        None,
    )
    if rec is None:
        return None
    hs = rec["hrvSamples"][0]
    vals = [float(v) for v in hs.get("hrvValues", [])]
    interval = int(float(str(hs.get("sampleInterval", "300s")).rstrip("s")) * 1000)
    naive = datetime.fromisoformat(hs["startTime"])
    out: dict[str, Any] = {
        "mean_rmssd": rec.get("meanNightlyRecoveryRmssd"),
        "n_values": len(vals),
        "mean_of_values": st.mean(vals) if vals else None,
        "alignments": {},
    }
    for name, zone in (("local", tz), ("utc", UTC)):
        t0 = naive.replace(tzinfo=zone).astimezone(UTC).timestamp() * 1000
        per_variant = {}
        for vname in ("filtro v0.3 (todas las reglas)", "solo contacto y rango"):
            segs = seg_rmssd(diffs_by_variant[vname], t0, len(vals), interval, min_diffs=20)
            pairs = [
                (math.log(a), math.log(v)) for a, v in zip(segs, vals, strict=False) if a and v > 0
            ]
            per_variant[vname] = _stats(pairs)
        out["alignments"][name] = per_variant
    return out


# ------------------------------------------------------------------- informe


def night_report(root: Path, sleep_date: date, tz: ZoneInfo) -> dict[str, Any]:
    sleep_doc = find_doc(
        root,
        "sleeps__dia.json",
        lambda d: any(
            n.get("sleepDate") == sleep_date.isoformat() and n.get("sleepResult")
            for n in d.get("nightSleeps", [])
        ),
    )
    if sleep_doc is None:
        raise NightError(
            f"No hay sueño guardado para {sleep_date}. Sincroniza Polar Flow y ejecuta "
            f"`ares polar-probe --day {sleep_date}`."
        )
    sleep = parse_sleep(sleep_doc, sleep_date)
    if sleep is None:
        raise NightError("El sueño guardado no trae inicio y fin.")
    prev_day = sleep_date - timedelta(days=1)
    docs = {d: find_doc(root, "ppi_samples__dia.json", _has_ppi(d)) for d in (prev_day, sleep_date)}
    if all(v is None for v in docs.values()):
        raise NightError(
            f"No hay PPI guardados. Ejecuta `ares polar-probe --day {prev_day}` y "
            f"`ares polar-probe --day {sleep_date}`."
        )
    beats: list[Beat] = []
    counts: dict[str, int] = {}
    for d, doc in docs.items():
        got = beats_from_doc(doc, d, tz) if doc else []
        counts[d.isoformat()] = len(got)
        beats += got
    beats.sort(key=lambda b: b.t)
    fl = flags(beats)
    mode, resid = detect_mode(beats)

    s_ms = int(sleep["start"].timestamp() * 1000)
    e_ms = int(sleep["end"].timestamp() * 1000)
    idx = [i for i, b in enumerate(beats) if s_ms <= b.t <= e_ms]
    win_beats = [beats[i] for i in idx]
    win_flags = [fl[i] for i in idx]
    dur_ms = e_ms - s_ms
    covered_h = sum(b.pp for b in win_beats) / 3.6e6

    # gap en el cambio de día
    junction = None
    a = [b for b in beats if b.t < day_start_ms(sleep_date, tz)]
    b0 = [b for b in beats if b.t >= day_start_ms(sleep_date, tz)]
    if a and b0:
        junction = (b0[0].t - a[-1].t) / 1000

    # ventana de cálculo: 30 min tras dormirse, 4 h
    w0, w1 = s_ms + WINDOW_OFFSET_MS, s_ms + WINDOW_OFFSET_MS + WINDOW_LEN_MS
    in_w = [i for i, b in enumerate(beats) if w0 <= b.t < w1]
    n_seg = WINDOW_LEN_MS // SEG_MS
    diffs_full = {name: valid_diffs(beats, fl, ign, mode) for name, ign in VARIANTS.items()}
    variants = {}
    for name, dfs in diffs_full.items():
        segs = seg_rmssd(dfs, w0, n_seg)
        med = _median_ms(segs)
        variants[name] = {
            "segments_ok": sum(v is not None for v in segs),
            "n_seg": n_seg,
            "rmssd_ms": med,
            "ln_rmssd": math.log(med) if med else None,
        }
    rule_counts = {r: sum(1 for i in in_w if r in fl[i]) for r in RULES}
    rejected = sum(1 for i in in_w if fl[i])
    nr_doc = find_doc(
        root,
        "nightly_recharge__dia.json",
        lambda d: any(
            r.get("sleepResultDate") == sleep_date.isoformat() and r.get("hrvSamples")
            for r in d.get("nightlyRechargeResults", [])
        ),
    )
    return {
        "date": sleep_date.isoformat(),
        "sleep": {
            "start": sleep["start"].astimezone(tz),
            "end": sleep["end"].astimezone(tz),
            "hours": dur_ms / 3.6e6,
            "zone": sleep["zone"],
            "battery": sleep["battery"],
        },
        "docs": counts,
        "mode": mode,
        "mode_resid_ms": resid,
        "junction_s": junction,
        "night": {
            "beats": len(win_beats),
            "covered_h": covered_h,
            "coverage_pct": 100 * covered_h * 3.6e6 / dur_ms if dur_ms else 0.0,
            "movement_pct": 100
            * sum("movimiento" in f for f in win_flags)
            / max(1, len(win_beats)),
            "error_pct": 100 * sum("error" in f for f in win_flags) / max(1, len(win_beats)),
            "first_min": (win_beats[0].t - s_ms) / 60000 if win_beats else None,
            "last_min": (win_beats[-1].t - e_ms) / 60000 if win_beats else None,
        },
        "window": {
            "beats": len(in_w),
            "rejected_pct": 100 * rejected / max(1, len(in_w)),
            "rules_pct": {r: 100 * c / max(1, len(in_w)) for r, c in rule_counts.items()},
        },
        "variants": variants,
        "nr": nr_comparison(nr_doc, sleep_date, diffs_full, tz) if nr_doc else None,
    }


SHORT = {"filtro v0.3 (todas las reglas)": "filtro v0.3", "solo contacto y rango": "contacto+rango"}


def _f(v: float | None, fmt: str = ".1f") -> str:
    return "—" if v is None else format(v, fmt)


def render(rep: dict[str, Any]) -> str:
    s, n, w = rep["sleep"], rep["night"], rep["window"]
    z = s["zone"]
    zone = f"{z.total_seconds() / 3600:+.0f} h" if z is not None else "sin zona"
    lines = [
        f"Noche del {rep['date']} · zona del sueño UTC{zone} · batería agotada: {s['battery']}",
        f"  Sueño: {s['start']:%H:%M} → {s['end']:%H:%M} ({s['hours']:.1f} h)",
        "  Intervalos por documento: "
        + ", ".join(f"{d}: {c}" for d, c in rep["docs"].items())
        + (
            f" · salto entre días: {rep['junction_s']:.0f} s"
            if rep["junction_s"] is not None
            else ""
        ),
        f"  Los desplazamientos marcan el {rep['mode']} de cada intervalo "
        f"(desviación mediana {_f(rep['mode_resid_ms'], '.0f')} ms)",
        "",
        "Toda la noche (inicio → fin del sueño)",
        f"  {n['beats']} intervalos · {n['covered_h']:.1f} h cubiertas "
        f"({n['coverage_pct']:.0f} % del sueño)",
        f"  primero {_f(n['first_min'], '+.0f')} min y último {_f(n['last_min'], '+.0f')} min "
        "respecto a los límites del sueño",
        f"  con movimiento: {n['movement_pct']:.0f} % · "
        f"con error > {MAX_ERR_MS} ms: {n['error_pct']:.0f} %",
        "",
        f"Ventana de cálculo (30 min después de dormirte, 4 h): {w['beats']} intervalos",
        "  rechazados por regla (una misma pulsación puede incumplir varias): "
        + " · ".join(f"{r} {p:.0f} %" for r, p in w["rules_pct"].items()),
        f"  rechazados en total: {w['rejected_pct']:.0f} %",
        "",
        "rMSSD según qué reglas se apliquen (mediana de segmentos de 5 min)",
    ]
    for name, v in rep["variants"].items():
        lines.append(
            f"  {name:<32} {v['segments_ok']:>2}/{v['n_seg']} segmentos · "
            f"rMSSD {_f(v['rmssd_ms'])} ms"
            f" · ln {_f(v['ln_rmssd'], '.2f')}"
        )
    nr = rep["nr"]
    lines.append("")
    if nr is None:
        lines.append("Nightly Recharge: sin muestras de esta noche en los ficheros de la sonda.")
    else:
        lines += [
            "Frente a Nightly Recharge de Polar",
            f"  media de la noche (Polar): {_f(nr['mean_rmssd'], '.0f')} ms · media de sus "
            f"{nr['n_values']} valores: {_f(nr['mean_of_values'])} ms",
        ]
        for al, per in nr["alignments"].items():
            for vname, stt in per.items():
                head = f"  alineación {al:<5} · {SHORT.get(vname, vname):<15}"
                if stt["n"] < 3:
                    lines.append(f"{head} pocos pares ({stt['n']})")
                else:
                    lines.append(
                        f"{head} n={stt['n']:>2} · sesgo ln {stt['bias_ln']:+.2f} · "
                        f"error abs. ln {stt['mae_ln']:.2f} · r {_f(stt['r'], '.2f')}"
                    )
    return "\n".join(lines)
