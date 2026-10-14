"""ARES LAB · pruebas offline; sin llavero, red ni datos personales reales."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from ares import db
from ares.app import lab_events
from ares.app.server import create_app
from ares.config import REPO_ROOT


ORIGIN = "http://127.0.0.1:8443"
HEADERS = {"Origin": ORIGIN, "X-ARES-LAB": "1"}


def event(kind="coffee", *, at=None, key=None, mg=100):
    payload = {
        "event_type": kind,
        "occurred_at": (at or datetime.now(UTC)-timedelta(seconds=2)).isoformat(),
        "client_event_key": str(key or uuid4()),
    }
    if kind == "coffee":
        payload.update(caffeine_mg=mg, amount_basis="estimated")
    return payload


def test_one_tap_cafe_idempotente_con_fuente_y_tiempo_real(conn, settings):
    api = TestClient(
        create_app(lambda: conn, settings, auto_sync=True), base_url=ORIGIN
    )
    body = event()
    first = api.post("/api/lab/events", json=body, headers=HEADERS)
    assert first.status_code == 201, first.text
    again = api.post("/api/lab/events", json=body, headers=HEADERS)
    assert again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert again.json()["already_saved"] is True
    assert first.json()["caffeine_mg"] == 100
    assert first.json()["amount_basis"] == "estimated"
    assert first.json()["source"] == "MANUAL · ARES LAB"
    assert conn.execute("SELECT count(*) FROM lab_events").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == 0


def test_hora_y_dosis_se_corrigen_sin_perder_traza_y_sin_duplicar(conn, settings):
    api=TestClient(create_app(lambda: conn,settings,auto_sync=True),base_url=ORIGIN)
    first=api.post("/api/lab/events",json=event(),headers=HEADERS).json()
    changed=(datetime.now(UTC)-timedelta(hours=2)).isoformat()
    patch=api.patch(
        f"/api/lab/events/{first['id']}",
        json={"occurred_at":changed,"caffeine_mg":60,"note":"espresso corto"},
        headers=HEADERS,
    )
    assert patch.status_code==200,patch.text
    assert patch.json()["caffeine_mg"]==60
    assert patch.json()["note"]=="espresso corto"
    assert conn.execute("SELECT count(*) FROM lab_events").fetchone()[0]==1
    assert conn.execute("SELECT created_at,updated_at FROM lab_events").fetchone() is not None
    hist=api.get("/api/lab/events").json()["events"]
    assert hist[0]["id"]==first["id"]
    assert hist[0]["local_time"]


def test_cena_y_cama_no_tienen_cafeina_y_borrado_es_logico(conn, settings):
    api=TestClient(create_app(lambda: conn,settings,auto_sync=True),base_url=ORIGIN)
    body=event("dinner_end")
    r=api.post("/api/lab/events",json=body,headers=HEADERS)
    assert r.status_code==201,r.text
    ident=r.json()["id"]
    assert r.json()["caffeine_mg"] is None
    assert api.patch(
        f"/api/lab/events/{ident}",json={"caffeine_mg":100},
        headers=HEADERS,
    ).status_code==422
    deleted=api.delete(f"/api/lab/events/{ident}",headers=HEADERS)
    assert deleted.status_code==200
    assert api.get("/api/lab/events").json()["count_30d"]==0
    assert conn.execute(
        "SELECT count(*) FROM lab_events WHERE deleted_at IS NOT NULL"
    ).fetchone()[0]==1
    assert api.post("/api/lab/events",json=body,headers=HEADERS).status_code==422
    assert api.post(
        "/api/lab/events",json=event("bedtime"),headers=HEADERS
    ).status_code==201


def test_solo_serve_mismo_origen_puede_escribir(conn, settings):
    read_only=TestClient(create_app(lambda: conn,settings),base_url=ORIGIN)
    assert read_only.get("/api/lab/events").status_code==200
    assert read_only.get("/api/lab/events").json()["write_enabled"] is False
    assert read_only.post("/api/lab/events",json=event(),headers=HEADERS).status_code==403
    active=TestClient(create_app(lambda: conn,settings,auto_sync=True),base_url=ORIGIN)
    assert active.post("/api/lab/events",json=event(),headers={
        "Origin":"https://sitio-ajeno.example","X-ARES-LAB":"1",
    }).status_code==403
    assert active.post("/api/lab/events",json=event(),
        headers={"Origin":ORIGIN}).status_code==403
    assert active.post("/api/lab/events",json=event(),
        headers={"X-ARES-LAB":"1"}).status_code==403
    assert conn.execute("SELECT count(*) FROM lab_events").fetchone()[0]==0


@pytest.mark.parametrize("bad",[
    {"event_type":"coffee","caffeine_mg":800,"amount_basis":"estimated"},
    {"event_type":"dinner_end","caffeine_mg":90},
    {"event_type":"coffee","caffeine_mg":100,"amount_basis":"invented"},
    {"event_type":"alcohol"},
    {"event_type":"coffee","caffeine_mg":-1,"amount_basis":"estimated"},
])
def test_validacion_estricta_no_guarda_entradas_invalidas(conn,settings,bad):
    api=TestClient(create_app(lambda:conn,settings,auto_sync=True),base_url=ORIGIN)
    body=event()
    body.update(bad)
    assert api.post("/api/lab/events",json=body,headers=HEADERS).status_code==422
    assert conn.execute("SELECT count(*) FROM lab_events").fetchone()[0]==0


def test_cambio_de_dia_y_dst_conserva_offset_real(conn,settings):
    local=datetime(2025,10,26,2,30,tzinfo=ZoneInfo("Europe/Madrid"),fold=1)
    data=lab_events.create(conn,settings.device_id,settings.tz,
        lab_events.NewEvent(**event("dinner_end",at=local)))
    assert data["local_date"]=="2025-10-26"
    assert data["local_time"]=="02:30"
    assert datetime.fromisoformat(data["occurred_at"]).utcoffset()==timedelta(0)


def test_id_ajeno_no_se_leak_ni_se_modifica(conn,settings):
    ident=lab_events.create(conn,"pulsera-otra",settings.tz,
        lab_events.NewEvent(**event()))
    with pytest.raises(LookupError):
        lab_events.get(conn,settings.device_id,settings.tz,ident["id"])
    assert lab_events.history(conn,settings.device_id,settings.tz)==[]


def test_migracion_005_no_altera_historico(conn):
    # conn fixture está en 005; todas las tablas anteriores deben seguir.
    assert db.current_version(conn)==5
    for tbl in ("raw_payload","daily_metrics","raw_h10_rr","job_runs"):
        assert conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name=?",
            [tbl],
        ).fetchone()[0]==1
    assert conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='lab_events'"
    ).fetchone()[0]==1


def seed_nights(conn,device_id,*,count=20,base=None):
    base=(base or datetime.now(UTC).replace(hour=20,minute=30,second=0,microsecond=0)
          -timedelta(days=1))
    for i in range(count):
        bedtime=base-timedelta(days=i)
        day=bedtime.astimezone(ZoneInfo("Europe/Madrid")).date()
        conn.execute(
            """INSERT INTO daily_metrics
               (local_sleep_date,device_id,sleep_start,sleep_end,rmssd_ms,rhr,
                sleep_min,score_state,quality,calibrating,night_check)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'SCORED','high',false,'ok')""",
            [day,device_id,bedtime,bedtime+timedelta(hours=7),
             54 if i<10 else 65,52 if i<10 else 48,410],
        )
    return base


def test_dinner_sleep_empieza_sin_evidencia_y_usa_la_ultima_cena_antes(conn,settings):
    empty=lab_events.dinner_sleep_analysis(conn,settings.device_id,settings.tz)
    assert empty["paired_nights"]==0
    assert not empty["ready_for_comparison"]
    base=seed_nights(conn,settings.device_id)
    for i in range(20):
        sleep=base-timedelta(days=i)
        # Diez noches <2 h, diez noches 3-4 h; sin inventar causas.
        dinner=sleep-timedelta(hours=1 if i<10 else 3,minutes=30 if i>=10 else 0)
        lab_events.create(conn,settings.device_id,settings.tz,
            lab_events.NewEvent(**event("dinner_end",at=dinner)))
    outcome=lab_events.dinner_sleep_analysis(conn,settings.device_id,settings.tz)
    assert outcome["paired_nights"]==20
    assert outcome["ready_for_comparison"] is True
    groups={b["label"]:b for b in outcome["bands"]}
    assert groups["<2 h"]["n"]==10
    assert groups["3–4 h"]["n"]==10
    assert groups["2–3 h"]["hrv_mean_ms"] is None
    assert groups["3–4 h"]["hrv_mean_ms"]==65
    assert "NO establecen causalidad" in outcome["method"]


def test_cohorte_pequena_no_presenta_medias_como_hallazgo(conn,settings):
    base=seed_nights(conn,settings.device_id,count=4)
    for i in range(4):
        lab_events.create(conn,settings.device_id,settings.tz,
            lab_events.NewEvent(**event("dinner_end",
                at=base-timedelta(days=i,hours=2,minutes=20))))
    d=lab_events.overview(conn,settings.device_id,settings.tz)
    assert d["dinner_sleep"]["paired_nights"]==4
    assert all(b["hrv_mean_ms"] is None for b in d["dinner_sleep"]["bands"])
    assert d["timeline"]
    assert d["count_30d"]==4


def test_idempotency_no_encubre_cambios_de_evento_con_misma_clave(conn,settings):
    key=uuid4()
    first=lab_events.create(conn,settings.device_id,settings.tz,
        lab_events.NewEvent(**event("coffee",key=key,mg=100)))
    fake=lab_events.create(conn,settings.device_id,settings.tz,
        lab_events.NewEvent(**event("coffee",key=key,mg=200)))
    assert first["id"]==fake["id"]
    assert fake["already_saved"] is True
    assert fake["caffeine_mg"]==100
