"""Comprobaciones sobre los modelos de intervals.icu con los datos reales de la cuenta.

No asumimos las constantes del modelo de forma y fatiga: se estiman a partir de tus
propios días. Con CTL_t = CTL_{t-1} + k·(carga_t − CTL_{t-1}) y k = 1 − e^(−1/τ),
la mediana de k diario da τ, la constante de tiempo real del modelo.
"""

from __future__ import annotations

import math
import statistics as st
from datetime import date
from typing import Any


def estimate_time_constant(
    rows: list[dict[str, Any]], load_key: str, value_key: str
) -> tuple[float | None, int]:
    """(τ estimada en días, nº de días usados). None si no hay datos suficientes."""
    ks: list[float] = []
    for a, b in zip(rows, rows[1:], strict=False):
        try:
            if (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days != 1:
                continue
            c0, c1, load = float(a[value_key]), float(b[value_key]), float(b[load_key])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(load - c0) < 1.0:  # denominador demasiado pequeño: ruido
            continue
        ks.append((c1 - c0) / (load - c0))
    if len(ks) < 5:
        return None, len(ks)
    k = st.median(ks)
    if not 0 < k < 1:
        return None, len(ks)
    return -1.0 / math.log(1.0 - k), len(ks)


def flat_keys(obj: Any, prefix: str = "", depth: int = 0) -> list[str]:
    """Claves con valor no vacío, hasta dos niveles de anidación (sin valores)."""
    out: list[str] = []
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        name = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 2:
            out.extend(flat_keys(v, name + ".", depth + 1))
        elif v not in (None, "", [], {}):
            out.append(name)
    return out
