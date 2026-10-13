"""El anonimizador de fixtures reales (scripts/record_whoop_fixtures.py), probado solo con
registros sintéticos: no se ejecuta el script, no se lee ninguna base ni se escribe nada."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from whoop_synthetic import merge, night

from ares.connectors import whoop

spec = importlib.util.spec_from_file_location(
    "record_whoop_fixtures",
    Path(__file__).parent.parent / "scripts" / "record_whoop_fixtures.py",
)
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)


def test_anonimiza_identificadores_de_forma_coherente_y_conserva_tiempos_y_valores():
    data = merge(night(987654, "2026-09-10"), night(987655, "2026-09-11"))
    anon = rec.Anonymizer()
    out = {e: [anon.record(e, r) for r in data[e]] for e in ("cycle", "sleep", "recovery")}
    for e, records in out.items():
        for r in records:
            assert r["user_id"] == 0 and "v1_id" not in r
            whoop.MODELS[e].model_validate(r)  # siguen cumpliendo el contrato
    assert [c["id"] for c in out["cycle"]] == [1000, 1001]
    assert [r["cycle_id"] for r in out["recovery"]] == [1000, 1001]
    assert [r["sleep_id"] for r in out["recovery"]] == [s["id"] for s in out["sleep"]]
    assert all(s["id"] not in {x["id"] for x in data["sleep"]} for s in out["sleep"])
    assert out["sleep"][0]["start"] == data["sleep"][0]["start"]
    assert out["sleep"][0]["timezone_offset"] == data["sleep"][0]["timezone_offset"]
    assert out["recovery"][0]["score"] == data["recovery"][0]["score"]
