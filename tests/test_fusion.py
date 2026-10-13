"""Medias por parejas WHOOP / COROS declarados vía Intervals.icu."""

from __future__ import annotations

from datetime import date

from ares.app import data, fusion
from ares.connectors.base import store_raw


DEVICE = "pulsera-principal"


def night(conn, day: str, *, sleep=420, hrv=50, rhr=50, quality="high"):
    conn.execute(
        """INSERT INTO daily_metrics
           (local_sleep_date, device_id, sleep_min, rmssd_ms, rhr,
            score_state, calibrating, quality)
           VALUES (?, ?, ?, ?, ?, 'SCORED', false, ?)""",
        [date.fromisoformat(day), DEVICE, sleep, hrv, rhr, quality],
    )


def coros(conn, day: str, *, sleep=450, hrv=60, rhr=54):
    store_raw(
        conn,
        source="intervals",
        endpoint="wellness",
        day=date.fromisoformat(day),
        body={
            "id": day, "sleepSecs": None if sleep is None else sleep * 60,
            "restingHR": rhr, "hrv": hrv, "ctl": 35,
        },
    )


def test_misma_fecha_media_50_50_y_gauges_ares(conn):
    night(conn, "2026-10-13", sleep=390, hrv=40, rhr=50)
    coros(conn, "2026-10-13", sleep=450, hrv=60, rhr=54)
    f = fusion.combine(conn, DEVICE, data.intervals_days(conn), source_device="COROS")
    assert f["matched_days"] == 1
    assert f["metric_pairs"] == {"sleep_min": 1, "rhr": 1, "hrv": 1}
    metrics = f["latest"]["metrics"]
    assert metrics["sleep_min"]["mean"] == 420
    assert metrics["rhr"]["mean"] == 52
    assert metrics["hrv"]["mean"] == 50
    assert metrics["hrv"]["kind"] == "EXP"
    assert metrics["rhr"]["kind"] == "CALC"
    assert f["device_verified"] is False
    result = data.home(conn, device="COROS", device_id=DEVICE)
    assert result["dials"][0]["value"] == "7:00"
    assert result["dials"][0]["tag"] == "CALC"
    assert result["dials"][1]["value"] == "50 ms"
    assert result["dials"][1]["tag"] == "EXP"
    assert result["dials"][2]["origin"] == "INTERVALS"


def test_no_mezcla_dias_distintos_y_muestra_falta_de_par(conn):
    night(conn, "2026-10-13")
    coros(conn, "2026-10-12")
    f = fusion.combine(conn, DEVICE, data.intervals_days(conn))
    assert f["latest_date"] == "2026-10-13"
    assert f["matched_days"] == 0
    assert all(item["mean"] is None for item in f["latest"]["metrics"].values())
    result = data.home(conn, device="COROS", device_id=DEVICE)
    assert result["dials"][0]["origin"] == "COROS vía INTERVALS"


def test_noche_whoop_excluida_no_entra_en_la_media(conn):
    night(conn, "2026-10-13", quality="excluded")
    coros(conn, "2026-10-13")
    f = fusion.combine(conn, DEVICE, data.intervals_days(conn))
    assert f["latest"]["whoop_valid"] is False
    assert f["matched_days"] == 0
    assert all(x["mean"] is None for x in f["latest"]["metrics"].values())


def test_ausencias_por_metrica_no_crean_valores_ni_renormalizan(conn):
    night(conn, "2026-10-13", sleep=None, hrv=None, rhr=48)
    coros(conn, "2026-10-13", sleep=410, hrv=77, rhr=None)
    f = fusion.combine(conn, DEVICE, data.intervals_days(conn))
    assert f["matched_days"] == 0
    assert f["metric_pairs"] == {"sleep_min": 0, "rhr": 0, "hrv": 0}
    assert all(x["mean"] is None for x in f["latest"]["metrics"].values())


def test_solo_parejas_validas_alimentan_la_serie_y_media_semanal(conn):
    night(conn, "2026-10-12", hrv=40)
    coros(conn, "2026-10-12", hrv=60)
    night(conn, "2026-10-13", hrv=60)
    coros(conn, "2026-10-13", hrv=80)
    f = fusion.combine(conn, DEVICE, data.intervals_days(conn))
    assert f["matched_days"] == 2
    assert [x["hrv"] for x in f["series"]] == [50, 70]
    assert data.home(conn, device="COROS", device_id=DEVICE)["dials"][1]["value"] == "60 ms"


def test_no_contamina_la_pulsera_ni_modifica_las_fuentes_originales(conn):
    night(conn, "2026-10-13")
    coros(conn, "2026-10-13")
    before = conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0]
    f = fusion.combine(conn, "otra-pulsera", data.intervals_days(conn))
    assert f["latest"] is None
    assert f["matched_days"] == 0
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == before


def test_sueno_sin_rango_plausible_no_crea_media(conn):
    night(conn, "2026-10-13", sleep=420, hrv=50, rhr=50)
    coros(conn, "2026-10-13", sleep=0, hrv=60, rhr=54)
    f = fusion.combine(conn, DEVICE, data.intervals_days(conn))
    assert f["latest"]["metrics"]["sleep_min"]["mean"] is None
    assert f["latest"]["metrics"]["hrv"]["mean"] == 55
    assert f["latest"]["metrics"]["rhr"]["mean"] == 52
