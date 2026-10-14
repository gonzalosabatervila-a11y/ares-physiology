"""El plan importado del maestro v9 y Fueling ARES v1.0: pruebas offline."""
from datetime import date

from fastapi.testclient import TestClient
import pytest

from ares.app import planning
from ares.app.server import create_app


def _day(week, weekday):
    return next(s for s in week["days"] if s["weekday"] == weekday)


def test_s32_sesiones_reales_y_fuerza_fuente_v9():
    p = planning.plan(today=date(2026, 10, 14))
    assert p["available"] and p["week"] == "S32"
    assert (p["start"], p["end"]) == ("2026-10-12", "2026-10-18")
    assert p["run_minutes"] == 477
    assert abs(p["run_km_approx"] - 81.3) < 0.01
    assert len(p["days"]) == 7
    tue = _day(p, "mar")
    assert tue["type"] == "CALIDAD"
    assert tue["duration_min"] == 80
    assert "4×2 km" in tue["title"]
    assert tue["strength_min"] == 60
    assert "35–40 g" in tue["nutrition"]["post_strength"]
    sat = _day(p, "sab")
    assert (sat["duration_min"], sat["km_estimate"]) == (135, 23.5)
    assert "105 min Z2" in sat["detail"]
    assert sat["nutrition"]["during"]["g_per_hour"] == [45, 45]
    assert sat["nutrition"]["during"]["basis"] == "EXCEL_MAESTRO"
    assert "no se compensan" in p["caveat"] or p["training_rules"]["no_compensation"]


def test_precarga_mira_mañana_y_las_reglas_de_fueling_are_sin_saltos():
    w = planning.plan(week="S32", today=date(2026, 10, 14))
    assert _day(w, "lun")["nutrition"]["category"] == "HIGH"  # prepara cruise MAR
    assert _day(w, "mie")["nutrition"]["category"] == "HIGH"  # prepara MLR JUE
    assert _day(w, "vie")["nutrition"]["category"] == "HIGH"  # prepara largo 135
    assert _day(w, "sab")["nutrition"]["category"] == "VERY HIGH"
    assert _day(w, "dom")["nutrition"]["category"] == "LOW"
    assert _day(w, "sab")["nutrition"]["during"]["g_per_hour"] == [45,45]
    assert "60–90" not in _day(w, "sab")["nutrition"]["during"]["text"]


def test_s33_pico_fuel_50_g_h_y_descarga_s34():
    peak = planning.plan(week="S33")
    assert (peak["run_minutes"],peak["run_km_approx"]) == (480, 82)
    assert _day(peak,"sab")["duration_min"] == 145
    assert _day(peak,"sab")["nutrition"]["during"]["g_per_hour"] == [50,50]
    assert _day(peak,"vie")["nutrition"]["category"] == "VERY HIGH"  # precarga largo >135
    deload = planning.plan(week="S34")
    assert deload["run_minutes"] == 360
    assert deload["run_km_approx"] > 60
    assert _day(deload,"sab")["duration_min"] == 120
    assert _day(deload,"sab")["nutrition"]["category"] == "HIGH"
    assert _day(deload,"mar")["strength_min"] == 45


def test_plan_por_fecha_fuera_del_snapshot_no_inventa_entrenamiento():
    missing = planning.plan(today=date(2027, 1, 1))
    assert missing["available"] is False
    assert "Fuera" in missing["reason"]
    assert missing["source_version"] == "v9 · 2026-10-08"
    assert planning.plan(week="S40", today=date(2027, 1, 1))["week"] == "S40"


def test_peso_opcional_no_publica_medicion_y_convierte_rangos_g_kg():
    p = planning.plan(week="S32")
    assert p["weight_kg"] is None
    assert _day(p,"mar")["nutrition"]["carbs_g"] is None
    active = planning.plan(week="S32", weight_kg=70.5)
    t = _day(active, "mar")["nutrition"]
    assert t["category"] == "HIGH"
    assert t["carbs_g_kg"] == [5, 6]
    assert 350 <= t["carbs_g"][0] <= 355
    assert 420 <= t["carbs_g"][1] <= 425
    assert t["protein_g"] == round(1.8*70.5)
    with pytest.raises(ValueError, match="no plausible"):
        planning.plan(week="S32", weight_kg=2)


def test_s35_documento_sin_ritmos_km_no_inventa_numeros():
    p = planning.plan(week="S35")
    assert p["run_km_approx"] is None
    assert _day(p, "lun")["km_estimate"] is None
    assert p["sync"] == "SNAPSHOT_MANUAL_NO_LIVE_DRIVE"
    assert _day(p,"sab")["nutrition"]["during"]["basis"] == "FUELING_V1_GUIDELINE"


def test_api_plan_y_home_comparten_la_misma_fuente_y_sin_escritura(conn, settings):
    c = TestClient(create_app(lambda: conn, settings))
    r = c.get("/api/plan?week=S32")
    assert r.status_code == 200
    assert r.json()["days"][0]["date"] == "2026-10-12"
    assert r.json()["source_version"] == "v9 · 2026-10-08"
    assert c.get("/api/plan?week=S70").status_code == 422
    home = c.get("/api/home")
    assert home.status_code == 200
    assert "plan_preview" in home.json()
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == 0
