"""Pruebas del laboratorio ARES · datos únicamente sintéticos."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from ares.app.physiology import report
from ares.app.server import create_app


DEVICE = "pulsera-principal"


def night(conn, d: date, *, device=DEVICE, rhr=50.0, hrv=51.0, sleep=420,
          quality="high", night_check="ok", scored="SCORED", calibrating=False):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, sleep_min, rmssd_ms, rhr,
            resp_rate, spo2, skin_temp, provider_recovery, score_state,
            calibrating, quality, night_check)
           VALUES (?, ?, ?, ?, ?, 14.8, 97, 32.1, 70, ?, ?, ?, ?)""",
        [d, device, sleep, hrv, rhr, scored, calibrating, quality, night_check],
    )


def metric(data, key):
    return next(m for m in data["metrics"] if m["key"] == key)


def test_base_sin_datos_no_inventa_mediciones(conn):
    r = report(conn, DEVICE)
    assert r["nights"] == r["usable_nights"] == 0
    assert r["anchor_date"] is None
    assert all(m["latest"] is None and m["reference"] is None for m in r["metrics"])


def test_referencia_28_dias_anteriores_no_solapada_y_cambio_estadistico(conn):
    end = date(2026, 10, 13)
    # 28 días previos a los 7 recientes (t-34 a t-7): FC 50.
    # 7 días recientes (t-6 a t): FC 55.
    for i in range(34, -1, -1):
        night(conn, end - timedelta(days=i), rhr=55 if i < 7 else 50)
    r = report(conn, DEVICE, days=90)
    m = metric(r, "rhr")
    assert (m["n7"], m["n28"], m["n_reference"]) == (7, 28, 28)
    assert m["latest"] == 55 and m["mean7"] == 55
    assert m["reference"] == 50
    assert m["difference"] == 5 and m["relative_change_pct"] == 10
    assert len(m["series"]) == 35
    assert r["nights"] == r["usable_nights"] == 35
    assert metric(r, "recovery")["origin"] == "MODELO · WHOOP"


def test_noche_pendiente_aparece_como_hueco_sin_recuperar_ayer(conn):
    yesterday = date(2026, 10, 12)
    night(conn, yesterday, hrv=61)
    night(conn, yesterday + timedelta(days=1), hrv=79,
          quality="excluded", scored="PENDING_SCORE", calibrating=None)
    r = report(conn, DEVICE)
    hrv = metric(r, "hrv")
    assert hrv["latest"] is None
    assert hrv["series"][-1] == {"date": "2026-10-13", "v": None}
    assert hrv["series"][0]["v"] == 61
    assert r["breakdown"]["excluded"] == 1
    assert r["usable_nights"] == 1


def test_bandera_zona_horaria_excluye_uso_pero_no_borra_historia(conn):
    night(conn, date(2026, 10, 12), hrv=61)
    night(conn, date(2026, 10, 13), hrv=79, night_check="offset_incoherente")
    r = report(conn, DEVICE)
    assert r["breakdown"]["night_flags"] == 1
    assert r["nights"] == 2 and r["usable_nights"] == 1
    assert metric(r, "hrv")["series"][-1]["v"] is None


def test_periodos_28_y_90_respetan_fechas_y_cuentan_entradas(conn):
    end = date(2026, 10, 13)
    for i in range(85):
        night(conn, end - timedelta(days=i))
    a = report(conn, DEVICE, days=28)
    b = report(conn, DEVICE, days=90)
    assert a["nights"] == 28 and len(metric(a, "hrv")["series"]) == 28
    assert b["nights"] == 85 and len(metric(b, "hrv")["series"]) == 85
    # Referencia usa registros anteriores aunque la gráfica solo enseñe 28 días.
    assert metric(a, "hrv")["n_reference"] == 28


def test_otro_dispositivo_no_contamina_la_serie(conn):
    night(conn, date(2026, 10, 13), device="otra-pulsera", rhr=100)
    assert report(conn, DEVICE)["nights"] == 0


def test_api_fisiologia_90_dias_y_periodo_invalido(conn, settings):
    night(conn, date(2026, 10, 13))
    client = TestClient(create_app(lambda: conn, settings))
    r = client.get("/api/fisiologia?days=90")
    assert r.status_code == 200
    assert r.json()["nights"] == 1 and r.json()["metrics"][0]["label"] == "Variabilidad cardíaca"
    assert client.get("/api/fisiologia?days=10").status_code == 422
