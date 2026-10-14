"""ARES Execution Intelligence: sesiones y noches verificables, no puntuaciones."""
from datetime import date

from ares.app import plan_execution, planning
from ares.connectors.base import store_raw


def record(conn, identity, day, start, *, detail=False, duration=3600,
           distance=10000, sport="running", add_private=False):
    body = {
        "_id" if detail else "id": identity,
        "date": start, "sportType": sport, "title": "Entrenamiento de prueba",
        "summary": {"duration": duration, "distance": distance, "heartrate": 140},
    }
    if add_private:
        body.update(notes="SECRETO-CORREDOR-001", gps=[{"lat": 0.01, "lon": 3}])
    store_raw(conn, source="tredict",
              endpoint="activity_detail" if detail else "activity",
              day=date.fromisoformat(day), body=body)


def analyze(conn, today=date(2026, 10, 14)):
    week = planning.plan(week="S32", today=today)
    return plan_execution.execution(
        conn, week["days"], device_id="pulsera-principal",
        tz="Europe/Madrid", today=today,
    )


def test_una_carrera_registrada_no_es_completada_y_no_exfiltra_info_privada(conn):
    record(conn, "test-001", "2026-10-12", "2026-10-12T05:30:00Z",
           add_private=True)
    out = analyze(conn)
    monday = out["days"]["2026-10-12"]
    assert monday["status"] == "observed_unverified"
    assert monday["verified_completion"] is False
    assert monday["count"] == 1
    assert monday["observed_minutes"] == 60
    assert monday["observed_km"] == 10
    assert monday["duration_difference_min"] == 0
    assert out["summary"]["verified_prescriptions"] == 0
    assert "SECRETO-CORREDOR-001" not in str(out)
    assert "gps" not in str(out)


def test_resumen_y_detalle_misma_carrera_no_cuentan_dos_veces(conn):
    record(conn, "same-123", "2026-10-12", "2026-10-12T05:30:00Z",
           duration=3600, distance=10000)
    record(conn, "same-123", "2026-10-12", "2026-10-12T05:30:00Z",
           detail=True, duration=3700, distance=10050)
    item = analyze(conn)["days"]["2026-10-12"]
    assert item["count"] == 1
    assert item["activities"][0]["has_detail"] is True
    assert item["observed_minutes"] == 61.7
    assert item["observed_km"] == 10.05


def test_sin_registro_no_es_no_cumplido_y_semana_futura_no_es_fallida(conn):
    now = analyze(conn)
    assert now["days"]["2026-10-12"]["status"] == "no_record_found"
    assert now["days"]["2026-10-16"]["status"] == "future"
    later = planning.plan(week="S37", today=date(2026, 10, 14))
    summary = plan_execution.execution(
        conn, later["days"], device_id="pulsera-principal",
        tz="Europe/Madrid", today=date(2026, 10, 14),
    )
    assert all(d["status"] == "future" for d in summary["days"].values())


def test_descanso_con_carrera_es_solo_observacion_sin_juicio(conn):
    record(conn, "run-rest", "2026-10-18", "2026-10-18T06:10:00Z")
    data = analyze(conn)["days"]["2026-10-18"]
    assert data["status"] == "rest_day_activity"
    assert not data["verified_completion"]


def test_varias_sesiones_no_se_atribuye_cambio_whoop_a_una(conn):
    record(conn, "run-1", "2026-10-12", "2026-10-12T05:30:00Z")
    record(conn, "run-2", "2026-10-12", "2026-10-12T11:00:00Z")
    monday = analyze(conn)["days"]["2026-10-12"]
    assert monday["count"] == 2
    assert monday["duration_difference_min"] is None
    assert monday["night_context"] is None


def test_zona_horaria_madrid_prevalece_sobre_dia_utc_en_cambio_de_fecha(conn):
    record(conn, "late-run", "2026-10-25", "2026-10-25T23:30:00Z")
    week = planning.plan(week="S34", today=date(2026, 10, 28))
    o = plan_execution.execution(
        conn, week["days"], device_id="pulsera-principal",
        tz="Europe/Madrid", today=date(2026, 10, 28),
    )
    assert o["days"]["2026-10-26"]["count"] == 1


def test_noche_antes_y_despues_solo_en_cronologia_real(conn):
    conn.execute(
        """INSERT INTO daily_metrics
        (local_sleep_date, device_id, sleep_min, rmssd_ms, rhr,
        provider_recovery, score_state, calibrating, quality, night_check,
        sleep_start, sleep_end)
        VALUES
        ('2026-10-12', 'pulsera-principal', 420, 60, 51,
         81, 'SCORED', false, 'high', 'ok',
         '2026-10-11T21:30:00Z', '2026-10-12T05:00:00Z'),
        ('2026-10-13', 'pulsera-principal', 400, 53, 55,
         60, 'SCORED', false, 'high', 'ok',
         '2026-10-12T21:30:00Z', '2026-10-13T05:00:00Z')"""
    )
    record(conn, "run-context", "2026-10-12", "2026-10-12T05:30:00Z")
    monday = analyze(conn)["days"]["2026-10-12"]
    n = monday["night_context"]
    assert n is not None
    assert n["before"]["rmssd_ms"] == 60
    assert n["after"]["rmssd_ms"] == 53
    assert n["difference"]["rmssd_ms"] == -7
    assert "No demuestra causalidad" in n["method"]
    assert monday["verified_completion"] is False
