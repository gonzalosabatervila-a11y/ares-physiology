"""Contrato del conector WHOOP v2 con fixtures sintéticas ajustadas al OpenAPI oficial.

Las respuestas reales anonimizadas no van a Git (~/ares-data/fixtures-private/); cuando
existan, los mismos modelos se validan contra ellas fuera del repositorio."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError
from whoop_synthetic import api, authorize_store, merge, night, utc, workout

from ares.config import get_secret, set_secret
from ares.connectors import whoop
from ares.connectors.base import ConnectorError

MADRID = ZoneInfo("Europe/Madrid")
DEVICE = "pulsera-principal"
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 10, 2, 7, 0, tzinfo=UTC)


def two_weeks() -> dict:
    nights = [night(1000 + i, f"2026-09-{10 + i:02d}") for i in range(14)]
    data = merge(*nights)
    data["workout"] = [workout(1, utc("2026-09-12T17:00"), utc("2026-09-12T18:00"))]
    return data


def sync(conn, http, tmp_path, endpoints=whoop.ALL_ENDPOINTS, token_http=None):
    return whoop.sync_whoop(
        conn,
        http,
        tmp_path,
        device_id=DEVICE,
        tz=MADRID,
        start=START,
        end=END,
        endpoints=endpoints,
        token_http=token_http,
    )


# ------------------------------------------------------------------- modelos del contrato


def test_las_fixtures_cumplen_los_modelos_del_openapi():
    data = two_weeks()
    for endpoint, records in data.items():
        for rec in records:
            whoop.MODELS[endpoint].model_validate(rec)


def test_un_sueno_sin_campos_obligatorios_no_cumple_el_contrato():
    rec = two_weeks()["sleep"][0]
    for field in ("nap", "timezone_offset", "cycle_id", "end"):
        broken = {k: v for k, v in rec.items() if k != field}
        with pytest.raises(ValidationError):
            whoop.Sleep.model_validate(broken)


def test_sin_puntuar_no_trae_score_y_es_valido():
    data = merge(night(1, "2026-09-10", state="PENDING_SCORE"))
    rec = whoop.Recovery.model_validate(data["recovery"][0])
    assert rec.score is None and rec.score_state == "PENDING_SCORE"


def test_step_count_puede_ser_nulo_y_el_ciclo_en_curso_no_tiene_fin():
    data = merge(night(1, "2026-09-10", steps=None, open_cycle=True))
    c = whoop.Cycle.model_validate(data["cycle"][0])
    assert c.step_count is None and c.end is None


def test_un_estado_de_puntuacion_desconocido_se_rechaza():
    rec = dict(two_weeks()["recovery"][0], score_state="SCORED_LATER")
    with pytest.raises(ValidationError):
        whoop.Recovery.model_validate(rec)


# ------------------------------------------------------------------- peticiones y páginas


def test_pagina_con_next_token_y_pide_limit_25_con_fechas_iso(conn, tmp_path):
    authorize_store(set_secret)
    seen: list[httpx.Request] = []
    res = sync(conn, api(two_weeks(), page_size=5, seen=seen), tmp_path, endpoints=("sleep",))
    assert res.fetched == 14
    urls = [urlparse(str(r.url)) for r in seen]
    assert [u.path for u in urls] == ["/developer/v2/activity/sleep"] * 3
    queries = [parse_qs(u.query) for u in urls]
    assert all(q["limit"] == ["25"] for q in queries)
    assert queries[0]["start"] == ["2026-09-01T00:00:00.000Z"]
    assert queries[0]["end"] == ["2026-10-02T07:00:00.000Z"]
    assert "nextToken" not in queries[0]
    assert queries[1]["nextToken"] == ["tok5"] and queries[2]["nextToken"] == ["tok10"]
    assert all(r.headers["Authorization"] == "Bearer acc-0" for r in seen)


def test_cada_registro_es_una_fila_en_bruto_con_su_dia_local(conn, tmp_path):
    authorize_store(set_secret)
    data = two_weeks()
    res = sync(conn, api(data), tmp_path)
    assert res.by_endpoint == {
        "recovery": (14, 14),
        "sleep": (14, 14),
        "cycle": (14, 14),
        "workout": (1, 1),
    }
    rows = conn.execute(
        "SELECT endpoint, day, device_id, body FROM raw_payload WHERE source='whoop' "
        "ORDER BY endpoint, day"
    ).fetchall()
    assert {r[2] for r in rows} == {DEVICE}
    bodies = {(r[0], json.dumps(json.loads(r[3]), sort_keys=True)) for r in rows}
    for endpoint, records in data.items():
        for rec in records:  # el registro se guarda tal cual llega
            assert (endpoint, json.dumps(rec, sort_keys=True)) in bodies
    # Día del sueño: fecha en Madrid de su inicio. Empieza a las 22:06 UTC del día 9, que en
    # Madrid ya son las 00:06 del 10: truncar el UTC daría el día equivocado.
    sleep_days = [r[1] for r in rows if r[0] == "sleep"]
    assert sleep_days[0].isoformat() == "2026-09-10"
    # Recovery no tiene start: fecha local de created_at
    rec_days = [r[1] for r in rows if r[0] == "recovery"]
    assert rec_days[0].isoformat() == "2026-09-10"
    for view in ("raw_whoop_recovery", "raw_whoop_sleep", "raw_whoop_cycle", "raw_whoop_workout"):
        assert conn.execute(f"SELECT count(*) FROM {view}").fetchone()[0] > 0


def test_repetir_no_duplica_y_un_registro_puntuado_despues_entra_como_version_nueva(conn, tmp_path):
    authorize_store(set_secret)
    pending = merge(night(1, "2026-09-10", state="PENDING_SCORE"))
    assert sync(conn, api(pending), tmp_path).inserted == 3  # ciclo, sueño y recuperación
    assert sync(conn, api(pending), tmp_path).inserted == 0
    scored = merge(night(1, "2026-09-10"))
    scored["recovery"][0]["updated_at"] = "2026-09-10T09:00:00.000Z"
    res = sync(conn, api(scored), tmp_path)
    assert res.by_endpoint["recovery"] == (1, 1)
    n = conn.execute("SELECT count(*) FROM raw_whoop_recovery").fetchone()[0]
    assert n == 2  # la versión anterior se queda: la capa bruta solo añade


def test_estado_por_endpoint_y_dispositivo_y_registro_del_dispositivo(conn, tmp_path):
    authorize_store(set_secret)
    sync(conn, api(two_weeks()), tmp_path)
    status = conn.execute(
        "SELECT endpoint, device_id, last_ok IS NOT NULL FROM source_status "
        "WHERE source='whoop' ORDER BY endpoint"
    ).fetchall()
    assert status == [(e, DEVICE, True) for e in sorted(whoop.ALL_ENDPOINTS)]
    dev = conn.execute(
        "SELECT device_id, model, provider, first_day, last_day FROM devices"
    ).fetchone()
    assert dev[:3] == (DEVICE, "WHOOP", "whoop")
    assert dev[3].isoformat() == "2026-09-10" and dev[4] >= dev[3]


def test_ante_401_renueva_una_vez_reintenta_y_guarda_el_par_nuevo(conn, tmp_path):
    authorize_store(set_secret)
    calls = {"n": 0}

    def status(request: httpx.Request) -> int | None:
        calls["n"] += 1
        return 401 if request.headers["Authorization"] == "Bearer acc-0" else None

    def token(request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        assert form["refresh_token"] == "ref-0" and form["scope"] == "offline"
        return httpx.Response(
            200, json={"access_token": "acc-1", "refresh_token": "ref-1", "expires_in": 3600}
        )

    res = sync(
        conn,
        api(two_weeks(), status=status),
        tmp_path,
        endpoints=("cycle",),
        token_http=httpx.Client(transport=httpx.MockTransport(token)),
    )
    assert res.fetched == 14
    assert get_secret("whoop_refresh_token") == "ref-1"
    assert get_secret("whoop_access_token") == "acc-1"


def test_un_error_del_servidor_queda_en_source_status_y_corta(conn, tmp_path):
    authorize_store(set_secret)
    http = api(two_weeks(), status=lambda r: 404)
    with pytest.raises(ConnectorError, match="404"):
        sync(conn, http, tmp_path, endpoints=("recovery",))
    row = conn.execute(
        "SELECT last_error IS NOT NULL, error FROM source_status WHERE source='whoop'"
    ).fetchone()
    assert row[0] and "404" in row[1]


def test_una_respuesta_sin_records_es_un_error_claro(conn, tmp_path):
    authorize_store(set_secret)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    from ares.connectors.base import HttpClient

    http = HttpClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(ConnectorError, match="records"):
        sync(conn, http, tmp_path, endpoints=("sleep",))


def test_el_token_nunca_aparece_en_el_estado_ni_en_lo_bruto(conn, tmp_path):
    authorize_store(set_secret)
    sync(conn, api(two_weeks()), tmp_path)
    dump = json.dumps(
        conn.execute("SELECT * FROM raw_payload").fetchall()
        + conn.execute("SELECT * FROM source_status").fetchall(),
        default=str,
    )
    assert "acc-0" not in dump and "ref-0" not in dump


def test_ventana_en_utc():
    now = datetime(2026, 10, 2, 7, 0, tzinfo=UTC)
    start, end = whoop.window(3, now)
    assert (start, end) == (now - timedelta(days=3), now)
