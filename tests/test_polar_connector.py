"""Conector de Polar con respuestas de la misma forma que las reales (29-30/09/2026):
`from` inclusivo y `to` exclusivo, `features` repetidas, PPI en filas normalizadas y solo un
resumen en raw_payload, sin duplicar nada al repetir la sincronización."""

from __future__ import annotations

import time
from datetime import date

import httpx
import pytest
import structlog

from ares import runner
from ares.connectors import polar
from ares.connectors.base import ConnectorError, HttpClient

DAY = date(2026, 9, 30)
UUID = "0e030000-0084-0000-0000-00001234abcd"


def ppi_doc(day: date, n: int = 6, start: int = 3625) -> dict:
    samples, t = [], start
    for i in range(n):
        samples.append(
            {
                "offsetMillis": t,
                "ppInterval": 1000 + i,
                "errorEstimateMillis": 5 + i,
                "skinContact": True,
                "movement": i % 2 == 0,
                "offline": False,
            }
        )
        t += 1000 + i
    return {
        "dailyPpiSamples": [
            {
                "date": day.isoformat(),
                "modified": "2026-09-30T04:00:00Z",
                "ppiSamplesPerDevice": [
                    {
                        "recordingDevice": {"uuid": UUID},
                        "ppiSamples": samples,
                        "recordingTriggerTypeChanges": [
                            {"triggerType": "TRIGGER_TYPE_AUTOMATIC", "offsetMillis": 1}
                        ],
                    }
                ],
            }
        ]
    }


SLEEPS = {
    "nightSleeps": [
        {
            "sleepDate": "2026-09-30",
            "sleepResult": {
                "hypnogram": {
                    "sleepStart": "2026-09-29T21:43:00.000+02:00",
                    "sleepEnd": "2026-09-30T05:15:00.000+02:00",
                }
            },
        }
    ]
}
EMPTY = {"nightSleeps": []}


def make(handler_by_path: dict, seen: list[httpx.Request]) -> HttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for suffix, fn in handler_by_path.items():
            if request.url.path.endswith(suffix):
                out = fn(request)
                return out if isinstance(out, httpx.Response) else httpx.Response(200, json=out)
        return httpx.Response(200, json={})

    return HttpClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )


def routes(day: date = DAY) -> dict:
    return {
        "/ppi-samples": lambda r: (
            ppi_doc(day) if r.url.params["from"] == day.isoformat() else {"dailyPpiSamples": []}
        ),
        "/sleeps": lambda r: SLEEPS if r.url.params["from"] == day.isoformat() else EMPTY,
    }


def test_las_llamadas_usan_to_exclusivo_features_repetidas_y_bearer(conn):
    seen: list[httpx.Request] = []
    polar.sync_polar(conn, make(routes(), seen), "tok", 1, today=DAY)
    sleeps = next(r for r in seen if r.url.path.endswith("/sleeps"))
    assert sleeps.url.params["from"] == "2026-09-30" and sleeps.url.params["to"] == "2026-10-01"
    assert sleeps.url.params.get_list("features") == [
        "sleep-result",
        "sleep-evaluation",
        "sleep-score",
    ]
    assert sleeps.headers["Authorization"] == "Bearer tok"
    wake = next(r for r in seen if r.url.path.endswith("/sleep-wake-vectors"))
    assert "features" not in wake.url.params
    assert len(seen) == len(polar.ENDPOINTS)  # un día, una llamada por endpoint


def test_guarda_los_ppi_normalizados_y_solo_un_resumen_en_raw_payload(conn):
    res = polar.sync_polar(conn, make(routes(), []), "tok", 1, today=DAY)
    assert res.ppi_rows == 6
    rows = conn.execute(
        "SELECT device_id, offset_ms, pp_ms, err_ms, skin_contact, movement, offline "
        "FROM raw_polar_ppi ORDER BY offset_ms"
    ).fetchall()
    assert rows[0] == (UUID, 3625, 1000, 5, True, True, False)
    assert rows[1][1] == 3625 + 1000 and rows[1][5] is False
    body = conn.execute(
        "SELECT body FROM raw_payload WHERE source='polar' AND endpoint='ppi-samples'"
    ).fetchone()[0]
    assert "ppiSamples" not in body and "n_samples" in body  # el documento entero no se duplica


def test_repetir_la_sincronizacion_no_duplica_nada(conn):
    polar.sync_polar(conn, make(routes(), []), "tok", 1, today=DAY)
    n_ppi = conn.execute("SELECT count(*) FROM raw_polar_ppi").fetchone()[0]
    n_raw = conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0]
    again = polar.sync_polar(conn, make(routes(), []), "tok", 1, today=DAY)
    assert again.ppi_rows == 0 and again.inserted == 0
    assert conn.execute("SELECT count(*) FROM raw_polar_ppi").fetchone()[0] == n_ppi
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == n_raw


def test_un_dia_que_crece_solo_anade_los_intervalos_nuevos(conn):
    small = {"/ppi-samples": lambda r: ppi_doc(DAY, n=4)}
    big = {"/ppi-samples": lambda r: ppi_doc(DAY, n=9)}
    first = polar.sync_polar(conn, make(small, []), "tok", 1, today=DAY)
    second = polar.sync_polar(conn, make(big, []), "tok", 1, today=DAY)
    assert first.ppi_rows == 4 and second.ppi_rows == 5
    assert conn.execute("SELECT count(*) FROM raw_polar_ppi").fetchone()[0] == 9
    versions = conn.execute(
        "SELECT count(*) FROM raw_payload WHERE endpoint='ppi-samples'"
    ).fetchone()[0]
    assert versions == 2  # dos resúmenes: el registro de cómo fue creciendo el día


def test_un_dia_sin_datos_no_guarda_documentos_vacios(conn):
    res = polar.sync_polar(conn, make({"/sleeps": lambda r: EMPTY}, []), "tok", 1, today=DAY)
    assert res.inserted == 0
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == 0


def test_varios_dias_piden_cada_dia_por_separado(conn):
    seen: list[httpx.Request] = []
    polar.sync_polar(conn, make({}, seen), "tok", 3, today=DAY)
    froms = sorted({r.url.params["from"] for r in seen})
    assert froms == ["2026-09-28", "2026-09-29", "2026-09-30"]
    assert len(seen) == 3 * len(polar.ENDPOINTS)


def test_estado_por_endpoint_y_un_fallo_no_tumba_a_los_demas(conn):
    handlers = {
        **routes(),
        "/sleep-wake-vectors": lambda r: httpx.Response(403, json={"error": "scope"}),
    }
    res = polar.sync_polar(conn, make(handlers, []), "tok", 1, today=DAY)
    assert "sleep-wake-vectors" in res.errors and res.ppi_rows == 6
    st = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT endpoint, last_ok IS NOT NULL FROM source_status WHERE source='polar'"
        ).fetchall()
    }
    assert st["ppi-samples"] is True and st["sleeps"] is True
    assert st["sleep-wake-vectors"] is False


def test_si_ninguna_llamada_responde_es_un_error(conn):
    everything_403 = {"": lambda r: httpx.Response(403, json={"error": "x"})}
    with pytest.raises(ConnectorError, match="ninguna llamada"):
        polar.sync_polar(conn, make(everything_403, []), "tok", 1, today=DAY)


def test_volumen_realista_de_un_dia_entra_deprisa(conn):
    t0 = time.time()
    res = polar.sync_polar(
        conn, make({"/ppi-samples": lambda r: ppi_doc(DAY, n=46_000)}, []), "tok", 1, today=DAY
    )
    assert res.ppi_rows == 46_000
    assert time.time() - t0 < 25


def test_runner_sin_autorizacion_omite_polar_con_un_mensaje_claro(conn, settings, monkeypatch):
    def sin_token():
        raise runner.polar_tokens.TokenError(
            "Este equipo no está autorizado en Polar: ejecuta ares polar-auth"
        )

    monkeypatch.setattr(runner.polar_tokens, "get_access_token", sin_token)
    with pytest.raises(runner.SyncSkipped, match="polar-auth"):
        runner.run_source_sync(conn, "polar", settings, logger=structlog.get_logger("t"))


def test_runner_sincroniza_polar_y_deja_el_registro(conn, settings, monkeypatch):
    monkeypatch.setattr(runner.polar_tokens, "get_access_token", lambda: "tok")
    hoy = date.today()
    http = make(
        {
            "/ppi-samples": lambda r: (
                ppi_doc(hoy) if r.url.params["from"] == hoy.isoformat() else {"dailyPpiSamples": []}
            )
        },
        [],
    )
    res = runner.run_source_sync(
        conn, "polar", settings, logger=structlog.get_logger("t"), http=http, days=1
    )
    assert res.source == "polar" and res.ppi_rows == 6
    job = conn.execute("SELECT job, status FROM job_runs ORDER BY started DESC LIMIT 1").fetchone()
    assert job == ("sync_polar", "ok")
