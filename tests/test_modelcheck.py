"""La constante de tiempo del modelo de forma/fatiga se estima con los propios datos."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from ares.app.modelcheck import estimate_time_constant, flat_keys


def series(tau: float, n: int = 60, rounding: int | None = None):
    random.seed(3)
    k = 1 - math.exp(-1 / tau)
    rows, ctl = [], 20.0
    for i in range(n):
        load = max(0.0, 45 + random.gauss(0, 25))
        ctl = ctl + k * (load - ctl)
        v = round(ctl, rounding) if rounding is not None else ctl
        rows.append(
            {
                "date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(),
                "ctlLoad": round(load, 1) if rounding is not None else load,
                "ctl": v,
            }
        )
    return rows


def test_recupera_la_constante_exacta_sin_ruido():
    tau, n = estimate_time_constant(series(42), "ctlLoad", "ctl")
    assert abs(tau - 42) < 0.05 and n > 40


def test_recupera_la_constante_corta_de_la_fatiga():
    tau, _ = estimate_time_constant(series(7), "ctlLoad", "ctl")
    assert abs(tau - 7) < 0.05


def test_con_los_datos_redondeados_a_un_decimal_sigue_cerca():
    tau, _ = estimate_time_constant(series(42, rounding=1), "ctlLoad", "ctl")
    assert 36 < tau < 50


def test_sin_campos_de_carga_no_inventa_nada():
    rows = [
        {"date": (date(2026, 8, 1) + timedelta(days=i)).isoformat(), "ctl": 30.0} for i in range(20)
    ]
    assert estimate_time_constant(rows, "ctlLoad", "ctl") == (None, 0)


def test_dias_no_consecutivos_no_cuentan():
    rows = series(42)
    saltado = [r for i, r in enumerate(rows) if i % 2 == 0]
    assert estimate_time_constant(saltado, "ctlLoad", "ctl")[0] is None


def test_flat_keys_solo_nombres_y_sin_valores_vacios():
    item = {
        "id": "x",
        "date": "2026-09-29",
        "vacio": None,
        "lista": [],
        "summary": {"duration": 10, "x": {"a": 1}},
    }
    assert flat_keys(item) == ["id", "date", "summary.duration", "summary.x.a"]
