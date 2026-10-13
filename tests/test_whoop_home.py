"""WHOOP directo en Inicio: nunca mezclar el origen con intervals.icu."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ares.app import data
from ares.app.server import create_app


def test_whoop_resumen_vacio_sin_valores_inventados(conn, settings):
    out = data.whoop_night_summary(conn, settings.device_id)
    assert out["source"] == "WHOOP directo"
    assert out["nights"] == 0
    assert out["valid_nights"] == 0
    assert out["latest"] is None


def test_whoop_muestra_ultima_noche_aunque_este_pendiente(conn, settings):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, sleep_min, rmssd_ms, rhr,
            provider_recovery, score_state, calibrating, quality, night_check)
           VALUES
           (DATE '2026-10-12', ?, 455, 50, 42, 80, 'SCORED',
            false, 'high', 'ok'),
           (DATE '2026-10-13', ?, NULL, NULL, NULL, NULL,
            'PENDING_SCORE', NULL, 'excluded', 'ok')""",
        [settings.device_id, settings.device_id],
    )
    result = data.whoop_night_summary(conn, settings.device_id)
    assert result["nights"] == 2
    assert result["valid_nights"] == 1
    assert result["qualities"] == {"high": 1, "fair": 0, "excluded": 1}
    assert result["latest"] == {
        "date": "2026-10-13",
        "sleep_min": None,
        "rmssd_ms": None,
        "rhr": None,
        "resp_rate": None,
        "spo2": None,
        "skin_temp": None,
        "provider_recovery": None,
        "score_state": "PENDING_SCORE",
        "calibrating": None,
        "quality": "excluded",
        "night_check": "ok",
    }


def test_api_home_trae_whoop_directo_sin_confundirlo_con_intervals(conn, settings):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, sleep_min, rmssd_ms, rhr,
            provider_recovery, score_state, calibrating, quality, night_check)
           VALUES (DATE '2026-10-13', ?, 421, 44.0, 39, 73.0,
                   'SCORED', false, 'high', 'ok')""",
        [settings.device_id],
    )
    result = TestClient(create_app(lambda: conn, settings)).get("/api/home")
    assert result.status_code == 200
    home = result.json()
    assert home["whoop"]["source"] == "WHOOP directo"
    assert home["whoop"]["valid_nights"] == 1
    assert home["whoop"]["latest"]["date"] == "2026-10-13"
    assert home["whoop"]["latest"]["rmssd_ms"] == 44.0
    # Las gráficas heredadas siguen explícitamente atribuidas a Intervals.
    assert home["dials"][0]["origin"] == "WHOOP vía INTERVALS"


def test_noche_de_otra_pulsera_no_contamina_el_resumen(conn, settings):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, quality, rmssd_ms)
           VALUES (DATE '2026-10-13', 'otra-pulsera', 'high', 30)"""
    )
    assert data.whoop_night_summary(conn, settings.device_id)["nights"] == 0
