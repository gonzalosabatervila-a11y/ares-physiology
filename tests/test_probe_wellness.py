"""El resumen de campos de bienestar cuenta presencia y rango sin exponer valores sueltos."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "probe_wellness", Path(__file__).parent.parent / "scripts" / "probe_wellness.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_cuenta_presencia_y_rangos_y_ignora_vacios():
    rows = [
        {"id": "2026-09-28", "hrv": 60.0, "restingHR": 48, "spO2": None, "comments": ""},
        {"id": "2026-09-29", "hrv": 70.5, "restingHR": 50, "readiness": 81, "note": "texto"},
        {"id": "2026-09-30", "hrv": 65.0, "readiness": 74, "ok": True},
    ]
    got = {k: (n, lo, hi) for k, n, lo, hi in probe.summarize(rows)}
    assert got["hrv"] == (3, 60.0, 70.5)
    assert got["restingHR"] == (2, 48.0, 50.0)
    assert got["readiness"] == (2, 74.0, 81.0)
    assert got["note"] == (1, None, None) and got["ok"] == (1, None, None)  # no numéricos
    assert "spO2" not in got and "comments" not in got and "id" not in got


def test_orden_de_mas_a_menos_presente():
    rows = [{"a": 1, "b": 1}, {"a": 2}, {"a": 3, "c": 1, "b": 2}]
    assert [k for k, *_ in probe.summarize(rows)] == ["a", "b", "c"]
