"""Línea base WHOOP en la portada: verdadera referencia individual (sintética)."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from ares.app.physiology import personal_baseline
from ares.app.server import create_app


DEVICE = "pulsera-principal"
NOW = date(2026, 10, 14)


def add_night(conn, when, *, device=DEVICE, hrv=60.0, rhr=50.0,
              sleep=420, resp=14.0, quality="high",
              score_state="SCORED", calibrating=False, night_check="ok"):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, sleep_min, rmssd_ms, rhr, resp_rate,
            score_state, calibrating, quality, night_check)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [when, device, sleep, hrv, rhr, resp, score_state,
         calibrating, quality, night_check],
    )


def fill_history(conn, *, n=65):
    for offset in range(n, 0, -1):
        add_night(conn, NOW - timedelta(days=offset))


def get_metric(out, key):
    return next(x for x in out["metrics"] if x["key"] == key)


def test_madura_60_noches_y_compara_ultima_fuera_de_linea_base(conn):
    fill_history(conn)
    add_night(conn, NOW, hrv=90, rhr=60, sleep=300, resp=16)
    out = personal_baseline(conn, DEVICE)
    assert out["ready"] is True
    assert out["status"] == "establecida"
    assert out["nights"] == 60 and out["window"] == 60
    assert out["anchor_date"] == "2026-10-14"
    assert out["latest_usable"] is True
    assert (get_metric(out, "hrv")["median"], get_metric(out, "hrv")["p25"],
            get_metric(out, "hrv")["p75"]) == (60, 60, 60)
    assert get_metric(out, "hrv")["latest"] == 90
    assert get_metric(out, "hrv")["delta"] == 30
    assert get_metric(out, "rhr")["median"] == 50
    assert get_metric(out, "sleep")["median"] == 420
    assert get_metric(out, "resp")["median"] == 14


def test_una_noche_pendiente_no_desplaza_la_ultima_valida(conn):
    fill_history(conn)
    add_night(conn, NOW, hrv=300, quality="excluded",
              score_state="PENDING_SCORE", calibrating=None)
    out = personal_baseline(conn, DEVICE)
    assert out["ready"] is True and out["status"] == "establecida"
    assert out["latest_usable"] is False
    assert get_metric(out, "hrv")["latest"] is None
    assert get_metric(out, "hrv")["median"] == 60


def test_excluye_noches_de_mala_calidad_y_puede_usar_dias_anteriores(conn):
    fill_history(conn)
    conn.execute(
        """UPDATE daily_metrics SET quality='excluded'
           WHERE device_id=? AND local_sleep_date=?""",
        [DEVICE, NOW - timedelta(days=3)],
    )
    add_night(conn, NOW, hrv=80)
    out = personal_baseline(conn, DEVICE)
    assert out["status"] == "establecida"
    assert get_metric(out, "hrv")["median"] == 60


def test_insuficientes_noches_no_inventan_referencia(conn):
    for i in range(1, 10):
        add_night(conn, NOW - timedelta(days=i))
    add_night(conn, NOW, hrv=55)
    out = personal_baseline(conn, DEVICE)
    assert out["status"] == "insuficiente"
    assert out["ready"] is False
    assert get_metric(out, "hrv")["median"] is None
    assert get_metric(out, "hrv")["delta"] is None


def test_no_confunde_pulseras_ni_metricas_con_datos_ausentes(conn):
    fill_history(conn)
    conn.execute(
        """UPDATE daily_metrics SET resp_rate=NULL
           WHERE device_id=?""",
        [DEVICE],
    )
    add_night(conn, NOW, resp=None)
    add_night(conn, NOW, device="otra-pulsera", hrv=1000, resp=40)
    out = personal_baseline(conn, DEVICE)
    assert out["status"] == "establecida"
    assert get_metric(out, "hrv")["median"] == 60
    assert get_metric(out, "resp")["median"] is None
    assert get_metric(out, "resp")["n"] == 0
    assert personal_baseline(conn, "otra-pulsera")["ready"] is False


def test_api_home_entrega_referencias_reales_sin_necesidad_de_decisiones(conn, settings):
    fill_history(conn)
    add_night(conn, NOW, hrv=53, sleep=354)
    client = TestClient(create_app(lambda: conn, settings))
    response = client.get("/api/home")
    assert response.status_code == 200
    data = response.json()
    assert data["estado"]["mode"] == "sombra"  # el entrenador no está activo
    baseline = data["personal_baseline"]
    assert baseline["ready"] is True and baseline["status"] == "establecida"
    assert get_metric(baseline, "hrv")["median"] == 60
    assert get_metric(baseline, "hrv")["latest"] == 53
    assert get_metric(baseline, "sleep")["median"] == 420
    assert get_metric(baseline, "sleep")["latest"] == 354
