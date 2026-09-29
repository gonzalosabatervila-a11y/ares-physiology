"""Sonda de solo lectura de la API v4 de Polar.

Hace la primera llamada real a cada endpoint que ARES va a usar y enseña la
ESTRUCTURA de lo que devuelve (claves, tipos, tamaños, rangos), no los valores.
Guarda cada respuesta en bruto en una carpeta local, fuera del repositorio y de
cualquier carpeta sincronizada, para poder escribir después el conector y sus
pruebas contra respuestas reales. No escribe nada en la base de datos.

Parámetros según la documentación oficial (https://www.polar.com/polar-api-v4/):
`from` inclusivo y `to` EXCLUSIVO, en ISO 8601; con `features` solo se admite un día.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypeGuard

import httpx

BASE_URL = "https://www.polaraccesslink.com/v4/data"
PLAIN_RANGE_DAYS = 7  # cabe en el máximo de todos los endpoints (el menor es 7 d)


@dataclass(frozen=True)
class Spec:
    name: str
    path: str
    features: tuple[str, ...] = ()


SPECS: tuple[Spec, ...] = (
    Spec("nightly_recharge", "/nightly-recharge-results", ("samples",)),
    Spec("sleeps", "/sleeps", ("sleep-result", "sleep-evaluation", "sleep-score")),
    Spec("sleep_wake_vectors", "/sleep-wake-vectors"),
    Spec("ppi_samples", "/ppi-samples", ("samples",)),
    Spec("continuous_samples", "/continuous-samples", ("heart-rate-samples",)),
    Spec("skin_contacts", "/skin-contacts"),
    Spec("activity", "/activity/list", ("samples",)),
    Spec("temperature", "/temperature-measurements"),
)


@dataclass(frozen=True)
class ProbeResult:
    name: str
    variant: str  # "rango" (sin features) | "dia" (con features)
    status: int | None
    note: str
    shape: list[str]
    saved: Path | None


# ---------------------------------------------------------------- estructura

_ENUM_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$")  # SLEEP_STATE_WAKE (lleva "_")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(?P<zone>Z|[+-]\d{2}:\d{2})?$"
)
_DURATION_RE = re.compile(r"^\d+(\.\d+)?s$")


def scalar_shape(value: Any) -> str:
    """Describe un valor sin revelarlo: tipo, formato o longitud."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if _ENUM_RE.match(value) and len(value) <= 48:
            return f"enum {value}"
        if _DATE_RE.match(value):
            return f"fecha {value}"  # las fechas sueltas dicen qué días hay datos
        m = _DATETIME_RE.match(value)
        if m:
            zone = m.group("zone")
            masked = re.sub(r"\d", "N", value[: m.start("zone")] if zone else value)
            return f"fecha/hora {masked}" + (f" zona={zone}" if zone else " (sin zona)")
        if _DURATION_RE.match(value):
            return "duración " + re.sub(r"\d", "N", value)
        return f"str(len={len(value)})"
    return type(value).__name__


def _is_num(x: Any) -> TypeGuard[int | float]:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _list_of_dicts_ranges(items: list[dict], pad: str, out: list[str]) -> None:
    """Rangos de las claves numéricas y recuentos de las booleanas, sobre toda la lista."""
    if len(items) < 2:
        return
    keys = list(items[0].keys())
    for k in keys:
        vals = [it.get(k) for it in items if isinstance(it, dict)]
        nums = [v for v in vals if _is_num(v)]
        bools = [v for v in vals if isinstance(v, bool)]
        if nums and len(nums) == len([v for v in vals if v is not None]):
            out.append(f"{pad}{k}: rango [{min(nums)} .. {max(nums)}]")
        elif bools:
            out.append(f"{pad}{k}: true={sum(bools)} false={len(bools) - sum(bools)}")


def describe(value: Any, name: str, indent: int, out: list[str]) -> None:
    pad = "  " * indent
    if isinstance(value, dict):
        out.append(f"{pad}{name}: objeto")
        for k, v in value.items():
            describe(v, k, indent + 1, out)
    elif isinstance(value, list):
        if not value:
            out.append(f"{pad}{name}: lista vacía")
            return
        out.append(f"{pad}{name}: lista de {len(value)}")
        first = value[0]
        if isinstance(first, dict):
            describe(first, "[0]", indent + 1, out)
            _list_of_dicts_ranges([v for v in value if isinstance(v, dict)], pad + "    ", out)
        elif _is_num(first):
            nums = [v for v in value if _is_num(v)]
            out.append(f"{pad}  valores: rango [{min(nums)} .. {max(nums)}]")
        else:
            out.append(f"{pad}  elementos: {scalar_shape(first)}")
    else:
        out.append(f"{pad}{name}: {scalar_shape(value)}")


def shape_of(body: Any) -> list[str]:
    out: list[str] = []
    describe(body, "respuesta", 0, out)
    return out


# ------------------------------------------------------------------ llamadas


def _get(
    client: httpx.Client,
    token: str,
    path: str,
    params: dict[str, Any],
    features: tuple[str, ...],
) -> tuple[httpx.Response, str]:
    """GET con `features` como clave repetida; si Polar responde 400 y hay más de una,
    reintenta con la lista separada por comas. Devuelve la respuesta y la variante usada."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = dict(params)
    if not features:
        return client.get(BASE_URL + path, params=base, headers=headers), ""
    resp = client.get(BASE_URL + path, params={**base, "features": list(features)}, headers=headers)
    if resp.status_code == 400 and len(features) > 1:
        alt = client.get(
            BASE_URL + path, params={**base, "features": ",".join(features)}, headers=headers
        )
        if alt.status_code != 400:
            return alt, "features separadas por comas"
    return resp, "features como clave repetida" if features else ""


def _save(out_dir: Path, name: str, variant: str, resp: httpx.Response) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}__{variant}.json"
    try:
        path.write_text(json.dumps(resp.json(), ensure_ascii=False, indent=1), encoding="utf-8")
    except ValueError:
        path.write_text(resp.text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # solo el propietario (en Windows se ignora en parte)
    except OSError:
        pass
    return path


def _run_one(
    client: httpx.Client,
    token: str,
    spec: Spec,
    variant: str,
    params: dict[str, Any],
    features: tuple[str, ...],
    out_dir: Path,
) -> ProbeResult:
    try:
        resp, how = _get(client, token, spec.path, params, features)
    except httpx.HTTPError as exc:
        return ProbeResult(spec.name, variant, None, f"sin conexión: {exc}", [], None)
    if resp.status_code != 200:
        detail = resp.text[:200].replace("\n", " ")
        return ProbeResult(
            spec.name, variant, resp.status_code, f"HTTP {resp.status_code}: {detail}", [], None
        )
    try:
        body = resp.json()
    except ValueError:
        return ProbeResult(spec.name, variant, 200, "200 pero no es JSON", [], None)
    saved = _save(out_dir, spec.name, variant, resp)
    return ProbeResult(spec.name, variant, 200, how or "OK", shape_of(body), saved)


def run_probe(
    token: str, day: date, out_dir: Path, client: httpx.Client | None = None
) -> list[ProbeResult]:
    """Para cada endpoint: una llamada de 7 días sin `features` (qué días hay datos)
    y, si el endpoint admite `features`, otra de ese único día con ellas."""
    http = client or httpx.Client(timeout=30.0)
    start = day - timedelta(days=PLAIN_RANGE_DAYS - 1)
    end_excl = day + timedelta(days=1)
    results: list[ProbeResult] = []
    for spec in SPECS:
        results.append(
            _run_one(
                http,
                token,
                spec,
                "rango",
                {"from": start.isoformat(), "to": end_excl.isoformat()},
                (),
                out_dir,
            )
        )
        if spec.features:
            results.append(
                _run_one(
                    http,
                    token,
                    spec,
                    "dia",
                    {"from": day.isoformat(), "to": end_excl.isoformat()},
                    spec.features,
                    out_dir,
                )
            )
    return results


def render(results: list[ProbeResult], out_dir: Path) -> str:
    lines: list[str] = []
    for r in results:
        head = f"── {r.name} · {r.variant} · " + (
            "OK" if r.status == 200 else (f"HTTP {r.status}" if r.status else "SIN RESPUESTA")
        )
        lines.append(head)
        if r.status != 200:
            lines.append(f"   {r.note}")
        else:
            if r.note not in ("OK", ""):
                lines.append(f"   ({r.note})")
            lines.extend("   " + s for s in r.shape)
        lines.append("")
    ok = sum(1 for r in results if r.status == 200)
    lines.append(f"{ok}/{len(results)} llamadas correctas")
    lines.append(f"Respuestas en bruto (datos de salud, solo en este equipo): {out_dir}")
    return "\n".join(lines)
