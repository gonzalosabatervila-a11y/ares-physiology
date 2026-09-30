"""La app enseña solo lo que hay: modo sombra, rangos personales calculados con los
días disponibles, campos ausentes sin romper nada y etiquetas de procedencia."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ares.app import data
from ares.app.server import create_app
from ares.connectors.base import mark_status, store_raw


def seed_intervals(conn, n: int = 10, *, hrv_last: float | None = None) -> None:
    for i in range(n):
        day = date(2026, 9, 1) + timedelta(days=i)
        rec = {
            "id": day.isoformat(),
            "sleepSecs": 27000 + 600 * (i % 3),
            "restingHR": 46 + i % 3,
            "hrv": 60.0 + (i % 4),
            "avgSleepingHR": 42 + i % 3,
            "ctl": 50.0 + i,
            "atl": 55.0 + i,
        }
        if i == n - 1 and hrv_last is not None:
            rec["hrv"] = hrv_last
        store_raw(conn, source="intervals", endpoint="wellness", day=day, body=rec)


def test_base_vacia_es_modo_sombra_sin_datos(conn):
    h = data.home(conn)
    assert h["estado"] == {"mode": "sombra", "nights": 0, "target": 21}
    assert [d["state"] for d in h["dials"]] == ["sin datos"] * 3
    assert all(s["value"] == "—" for s in h["signals"])
    assert h["steps"] is None and h["days"] == 0


def test_pocos_dias_no_inventan_un_rango(conn):
    seed_intervals(conn, n=4)
    noche = data.home(conn)["dials"][0]
    assert noche["state"].startswith("sin rango") and "4/7" in noche["state"]
    assert noche["p"] is None and noche["band"] is None
    assert noche["value"] != "—"


def test_rango_personal_y_estado_de_la_aguja(conn):
    seed_intervals(conn, n=30)
    nervioso = data.home(conn)["dials"][1]
    assert nervioso["state"] == "en rango" and nervioso["level"] == "ok"
    assert 0.0 <= nervioso["p"] <= 1.0 and nervioso["band"][0] < nervioso["band"][1]
    assert (nervioso["tag"], nervioso["origin"]) == ("MED", "INTERVALS")


def test_una_noche_suelta_baja_no_saca_la_media_de_7_dias_del_rango(conn):
    """La regla compara la media de 7 días con la franja diaria: una noche mala aislada
    no debe encender el aviso (esa es la razón de usar la media). Serie con el ruido
    diario realista de una VFC (alterna 54 y 68 ms) y una última noche a 52 ms."""
    values = [54.0 if i % 2 == 0 else 68.0 for i in range(29)] + [52.0]
    for i, v in enumerate(values):
        day = date(2026, 9, 1) + timedelta(days=i)
        store_raw(
            conn,
            source="intervals",
            endpoint="wellness",
            day=day,
            body={"id": day.isoformat(), "hrv": v, "sleepSecs": 27000},
        )
    d = data.home(conn)["dials"][1]
    assert d["state"] == "en rango" and d["level"] == "ok"


def test_una_semana_baja_si_marca_por_debajo_como_aviso(conn):
    seed_intervals(conn, n=30)
    for i in range(23, 30):  # última semana claramente baja
        day = date(2026, 9, 1) + timedelta(days=i)
        store_raw(
            conn,
            source="intervals",
            endpoint="wellness",
            day=day,
            body={"id": day.isoformat(), "hrv": 50.0, "sleepSecs": 27000},
        )
    d = data.home(conn)["dials"][1]
    assert d["state"] == "por debajo" and d["level"] == "warn"


def test_por_encima_es_informativo_no_aviso(conn):
    seed_intervals(conn, n=30)
    for i in range(23, 30):
        day = date(2026, 9, 1) + timedelta(days=i)
        store_raw(
            conn,
            source="intervals",
            endpoint="wellness",
            day=day,
            body={"id": day.isoformat(), "hrv": 75.0, "sleepSecs": 27000},
        )
    d = data.home(conn)["dials"][1]
    assert d["state"] == "por encima" and d["level"] == "none"


def test_carga_no_juzga_solo_describe_la_tendencia(conn):
    seed_intervals(conn, n=12)
    carga = data.home(conn)["dials"][2]
    assert carga["state"] in {"sube", "baja", "estable"} and carga["state"] == "sube"
    assert (carga["tag"], carga["origin"]) == ("CALC", "INTERVALS")


def test_campos_ausentes_o_nulos_no_rompen(conn):
    for i in range(3):
        day = date(2026, 9, 1) + timedelta(days=i)
        store_raw(
            conn,
            source="intervals",
            endpoint="wellness",
            day=day,
            body={"id": day.isoformat(), "hrv": None, "sleepSecs": "no-numero"},
        )
    h = data.home(conn)
    assert h["dials"][0]["state"] == "sin datos"


def test_se_usa_la_ultima_version_de_cada_dia(conn):
    day = date(2026, 9, 1)
    store_raw(
        conn,
        source="intervals",
        endpoint="wellness",
        day=day,
        body={"id": day.isoformat(), "restingHR": 50},
    )
    store_raw(
        conn,
        source="intervals",
        endpoint="wellness",
        day=day,
        body={"id": day.isoformat(), "restingHR": 47},
    )
    assert data.intervals_days(conn)[-1]["restingHR"] == 47


def test_fuentes_frescura_y_polar_sin_conector(conn):
    mark_status(conn, source="intervals", endpoint="wellness", ok=True)
    mark_status(conn, source="tredict", endpoint="activity", ok=False, error="HTTP 401")
    now = datetime.now(UTC) + timedelta(hours=2)
    by = {s["source"]: s for s in data.sources(conn, now)}
    assert by["intervals"]["level"] == "ok" and by["intervals"]["age_min"] >= 120
    assert by["tredict"]["level"] == "bad" and by["tredict"]["error"] == "HTTP 401"
    assert by["polar"]["level"] == "none" and "no ha sincronizado" in by["polar"]["error"]
    old = datetime.now(UTC) + timedelta(hours=20)
    assert {s["source"]: s["level"] for s in data.sources(conn, old)}["intervals"] == "warn"


def test_actividades_de_tredict_solo_la_ultima_version(conn):
    store_raw(
        conn,
        source="tredict",
        endpoint="activity",
        day=date(2026, 9, 26),
        body={"id": "a1", "date": "2026-09-26T06:00:00.000Z", "sportType": "running"},
    )
    store_raw(
        conn,
        source="tredict",
        endpoint="activity",
        day=date(2026, 9, 20),
        body={"id": "a0", "date": "2026-09-20T06:00:00.000Z", "sportType": "strength"},
    )
    acts = data.progreso(conn)["activities"]
    assert [a["sport"] for a in acts] == ["running", "strength"]
    assert acts[0]["date"] == "2026-09-26"


def test_estado_activo_solo_con_21_noches_y_una_decision(conn):
    conn.execute(
        "INSERT INTO decisions (d, level, signals, input_hash, metrics_snapshot, "
        "rules_version, generated_at) VALUES (DATE '2026-10-20', 'sin_cambios', '{}', "
        "'h', '{}', '1.2', now())"
    )
    assert data.estado(conn)["mode"] == "sombra"  # hay decisión pero faltan noches


@pytest.fixture
def client(conn, settings):
    return TestClient(create_app(lambda: conn, settings))


def test_rutas_http(client, conn):
    seed_intervals(conn, n=10)
    home = client.get("/api/home")
    assert home.status_code == 200 and home.json()["estado"]["mode"] == "sombra"
    assert client.get("/api/progreso").json()["ctl"]
    lab = client.get("/api/lab").json()
    assert lab["gate"]["level"] == "sin evaluar" and lab["versions"]["schema"] == 3
    page = client.get("/")
    assert page.status_code == 200 and "ARES" in page.text
    assert page.headers["cache-control"].startswith("no-store")
    js = client.get("/static/app.js")
    assert js.status_code == 200 and js.headers["cache-control"].startswith("no-store")
    assert client.get("/docs").status_code == 404  # sin documentación pública de la API


def test_sync_manual_llama_al_scheduler(conn, settings):
    calls = []
    c = TestClient(create_app(lambda: conn, settings, sync_now=lambda: calls.append(1)))
    r = c.post("/api/sync")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert calls == [1]


def test_sync_manual_no_disponible_en_app_suelta(client):
    r = client.post("/api/sync")
    assert r.status_code == 503


def test_fmt_hm():
    assert data.fmt_hm(7.6333) == "7:38"
    assert data.fmt_hm(8.0) == "8:00"


def test_senales_usan_solo_campos_que_trae_la_cuenta_real(conn):
    """Campos reales de intervals.icu verificados en la cuenta de Gonzalo (29/09/2026):
    hrv, restingHR, sleepSecs, avgSleepingHR, ctl, atl y steps. `sleepScore` no existe."""
    seed_intervals(conn, n=10)
    labels = [s["label"] for s in data.home(conn)["signals"]]
    assert any(label.startswith("Pulso durante el sueño") for label in labels)
    assert not any("Puntuación" in label for label in labels)
    valores = {s["label"]: s["value"] for s in data.home(conn)["signals"]}
    assert valores["Pulso durante el sueño · última noche"] != "—"


def test_la_senal_dice_que_valor_muestra_y_da_la_media_de_7_dias_como_el_indicador(conn):
    """El indicador enseña la media de 7 días y la fila la última noche: la etiqueta y la
    nota deben decirlo, para que 56 ms arriba y 50 ms abajo no parezcan una contradicción."""
    values = [54.0 if i % 2 == 0 else 68.0 for i in range(29)] + [50.0]
    for i, v in enumerate(values):
        day = date(2026, 9, 1) + timedelta(days=i)
        store_raw(
            conn,
            source="intervals",
            endpoint="wellness",
            day=day,
            body={"id": day.isoformat(), "hrv": v},
        )
    h = data.home(conn)
    fila = next(s for s in h["signals"] if s["label"].startswith("VFC"))
    assert fila["label"] == "VFC · última noche" and fila["value"] == "50 ms"
    assert fila["note"].startswith("media 7 d: 59")  # (68+54+68+54+68+54+50)/7 = 59,4
    assert h["dials"][1]["value"] == "59 ms"  # el indicador usa esa misma media de 7 días


# ------------------------------------------------------- rediseño: tendencias y detalle


def seed_days(conn, n: int, **fields) -> None:
    for i in range(n):
        day = date(2026, 9, 1) + timedelta(days=i)
        rec = {
            "id": day.isoformat(),
            "hrv": 60.0 + (i % 5),
            "sleepSecs": 26000 + 300 * (i % 4),
            "restingHR": 46 + i % 3,
            "avgSleepingHR": 42 + i % 2,
            "ctl": 30.0 + i,
            "atl": 33.0 + i,
        }
        rec.update({k: (v(i) if callable(v) else v) for k, v in fields.items()})
        store_raw(conn, source="intervals", endpoint="wellness", day=day, body=rec)


def test_tendencias_de_los_indicadores_solo_con_datos_suficientes(conn):
    seed_days(conn, 4)
    assert [d["trend"] for d in data.home(conn)["dials"]] == [None, None, None]


def test_tendencias_de_los_indicadores_con_30_dias(conn):
    seed_days(conn, 30)
    noche, nervioso, carga = data.home(conn)["dials"]
    assert noche["trend"].endswith(" min vs 7 d")
    assert nervioso["trend"].endswith(" ms vs tu media")
    assert carga["trend"].endswith(" % en 7 d") and carga["trend"].startswith("+")
    assert (noche["signal"], nervioso["signal"], carga["signal"]) == ("sleep", "hrv", "ctl")


def test_la_tendencia_de_carga_es_la_variacion_real_de_7_dias(conn):
    seed_days(conn, 30)  # ctl = 30 + i: hoy 59, hace 7 días 52
    assert data.home(conn)["dials"][2]["trend"] == f"+{round((59 / 52 - 1) * 100)} % en 7 d"


def test_las_senales_llevan_clave_y_serie_para_la_minigrafica(conn):
    seed_days(conn, 30)
    filas = {s["key"]: s for s in data.home(conn)["signals"]}
    assert list(filas) == ["hrv", "rhr", "sleep", "sleep_hr", "ctl"]
    assert len(filas["hrv"]["spark"]) == 14 and filas["hrv"]["unit"] == "ms"


def test_detalle_de_senal_ventanas_y_procedencia(conn):
    seed_days(conn, 30)
    d7 = data.signal_detail(conn, "hrv", 7)
    assert len(d7["series"]) == 7 and d7["partial"] is False
    d365 = data.signal_detail(conn, "hrv", 365)
    assert d365["partial"] is True and d365["available_days"] == 30
    assert len(d365["series"]) == 30
    assert d365["range"]["lo"] < d365["range"]["hi"] and d365["n_ref"] == 30
    assert d365["coverage"] == 100 and d365["origin"] == "INTERVALS"
    assert d365["nature"].startswith("MED") and d365["state"] in {
        "en rango",
        "por encima",
        "por debajo",
    }
    assert d365["stats"]["last"] == d365["value"]
    assert d365["periods"] == [7, 28, 90, 365]


def test_detalle_sueno_juzga_la_ultima_noche_y_hrv_la_media_de_7_dias(conn):
    seed_days(conn, 30)
    assert data.signal_detail(conn, "sleep", 28)["agg"] == "last"
    assert data.signal_detail(conn, "hrv", 28)["agg"] == "mean7"


def test_detalle_avisa_solo_por_el_lado_peligroso(conn):
    # Pulso en reposo: avisa si SUBE; si baja es informativo.
    seed_days(conn, 30, restingHR=lambda i: 46 + i % 3 + (12 if i >= 23 else 0))
    alto = data.signal_detail(conn, "rhr", 28)
    assert alto["state"] == "por encima" and alto["level"] == "warn"
    seed_days(conn, 30, restingHR=lambda i: 46 + i % 3 - (12 if i >= 23 else 0))
    bajo = data.signal_detail(conn, "rhr", 28)
    assert bajo["state"] == "por debajo" and bajo["level"] == "none"


def test_detalle_con_pocos_dias_no_inventa_rango(conn):
    seed_days(conn, 4)
    d = data.signal_detail(conn, "hrv", 28)
    assert d["range"] is None and d["state"].startswith("sin rango")
    assert d["interpretation"]["title"] == "Aún no hay rango habitual"


def test_detalle_carga_describe_tendencia_sin_juzgar(conn):
    seed_days(conn, 30)
    d = data.signal_detail(conn, "ctl", 28)
    assert d["state"] == "sube" and d["level"] == "ok" and d["nature"].startswith("CALC")
    assert "no lo interpreta como bueno o malo" in d["interpretation"]["text"]


def test_detalle_sin_datos_no_rompe(conn):
    d = data.signal_detail(conn, "hrv", 28)
    assert d["empty"] is True and d["label"] == "VFC"


def test_la_procedencia_no_atribuye_a_un_dispositivo_que_la_api_no_dice(conn):
    seed_days(conn, 10)
    d = data.signal_detail(conn, "hrv", 28)
    assert "COROS" not in str(d) and "Tredict" not in str(d)


def test_sesiones_por_semana_de_tredict(conn):
    hoy = date(2026, 9, 29)  # martes; su semana empieza el lunes 28
    for k, (dia, deporte) in enumerate(
        [
            (date(2026, 9, 29), "running"),
            (date(2026, 9, 28), "running"),
            (date(2026, 9, 22), "misc"),
            (date(2026, 9, 21), "running"),
            (date(2026, 8, 1), "running"),
        ]
    ):
        store_raw(
            conn,
            source="tredict",
            endpoint="activity",
            day=dia,
            body={"id": f"a{k}", "date": f"{dia.isoformat()}T06:00:00.000Z", "sportType": deporte},
        )
    semanas = data.weekly_sessions(conn, today=hoy)
    assert len(semanas) == 8 and semanas[-1]["week"] == "2026-09-28"
    assert (semanas[-1]["sessions"], semanas[-1]["running"]) == (2, 2)
    assert (semanas[-2]["sessions"], semanas[-2]["running"]) == (2, 1)
    assert sum(w["sessions"] for w in semanas) == 4  # la del 1 de agosto queda fuera de 8 semanas


def test_progreso_expone_forma_fatiga_y_balance(conn):
    seed_days(conn, 30, rampRate=lambda i: 1.5)
    p = data.progreso(conn)
    assert p["stats"]["ctl"] == 59.0 and p["stats"]["atl"] == 62.0
    assert p["stats"]["form"] == -3.0 and p["stats"]["ramp"] == 1.5


def test_fuentes_incluyen_la_hora_del_ultimo_exito(conn):
    mark_status(conn, source="intervals", endpoint="wellness", ok=True)
    by = {s["source"]: s for s in data.sources(conn)}
    assert by["intervals"]["last_ok"] is not None and by["polar"]["last_ok"] is None


def test_ruta_de_detalle_de_senal(client, conn):
    seed_days(conn, 30)
    ok = client.get("/api/senal/hrv?days=28")
    assert ok.status_code == 200 and ok.json()["label"] == "VFC"
    assert client.get("/api/senal/no_existe").status_code == 404
    assert client.get("/api/senal/hrv?days=13").status_code == 422


def test_la_carga_no_muestra_franja_normal_porque_no_se_juzga(conn):
    seed_days(conn, 30)
    noche, nervioso, carga = data.home(conn)["dials"]
    assert carga["band"] is None and carga["p"] is not None
    assert noche["band"] is not None and nervioso["band"] is not None


# --------------------------------------------------- icono y pantalla completa del iPhone


def _png_size(data: bytes) -> tuple[int, int]:
    import struct

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manifiesto_e_iconos_para_la_pantalla_de_inicio(client):
    import json

    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200 and "manifest+json" in r.headers["content-type"]
    m = json.loads(r.text)
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["name"] == "ARES"
    for icon in m["icons"]:
        png = client.get(icon["src"])
        assert png.status_code == 200
        w, h = _png_size(png.content)
        assert f"{w}x{h}" == icon["sizes"]


def test_la_pagina_declara_el_icono_de_iphone_y_el_manifiesto(client):
    html = client.get("/").text
    assert 'rel="apple-touch-icon" href="/static/icon-180.png"' in html
    assert 'rel="manifest" href="/static/manifest.webmanifest"' in html
    assert "apple-mobile-web-app-capable" in html
    png = client.get("/static/icon-180.png").content
    assert _png_size(png) == (180, 180)


# ------------------------------------------- sueño, VFC, pulso y pasos desde la Loop


def _sleep_doc(day, secs):
    return {
        "nightSleeps": [
            {
                "sleepDate": day,
                "sleepResult": {"hypnogram": {}},
                "sleepEvaluation": {"sleepSpan": f"{secs + 1800}s", "asleepDuration": f"{secs}s"},
            }
        ]
    }


def _nr_doc(day, rmssd, rri):
    return {
        "nightlyRechargeResults": [
            {
                "sleepResultDate": day,
                "meanNightlyRecoveryRmssd": rmssd,
                "meanNightlyRecoveryRri": rri,
            }
        ]
    }


def _act_doc(day, *devices):
    """devices: [(deviceId, [pasos por minuto…]), …]"""
    return {
        "activityDays": [
            {
                "date": day,
                "activitiesPerDevice": [
                    {
                        "deviceReference": {"deviceId": dev},
                        "activitySamples": [
                            {
                                "stepSamples": {
                                    "startTime": "00:00:00",
                                    "interval": 60000,
                                    "steps": steps,
                                }
                            }
                        ],
                    }
                    for dev, steps in devices
                ],
            }
        ]
    }


def seed_loop(
    conn,
    n: int = 10,
    *,
    secs=lambda i: 26000 + 300 * (i % 4),
    rmssd=lambda i: 60 + (i % 5),
    steps=lambda i: [3, 4, 5 + i],
) -> None:
    for i in range(n):
        d = date(2026, 9, 20) + timedelta(days=i)
        day = d.isoformat()
        store_raw(conn, source="polar", endpoint="sleeps", day=d, body=_sleep_doc(day, secs(i)))
        store_raw(
            conn,
            source="polar",
            endpoint="nightly-recharge-results",
            day=d,
            body=_nr_doc(day, rmssd(i), 1100 + 10 * (i % 3)),
        )
        store_raw(
            conn,
            source="polar",
            endpoint="activity",
            day=d,
            body=_act_doc(day, ("LOOP0001", steps(i))),
        )


def test_loop_days_lee_sueno_vfc_pulso_y_pasos(conn):
    d = date(2026, 9, 30)
    store_raw(conn, source="polar", endpoint="sleeps", day=d, body=_sleep_doc("2026-09-30", 26400))
    store_raw(
        conn,
        source="polar",
        endpoint="nightly-recharge-results",
        day=d,
        body=_nr_doc("2026-09-30", 65, 1100),
    )
    store_raw(
        conn,
        source="polar",
        endpoint="activity",
        day=d,
        body=_act_doc("2026-09-30", ("A", [1, 2, 3]), ("B", [10, 20])),
    )
    (rec,) = data.loop_days(conn)
    assert rec["date"] == "2026-09-30" and rec["sleep_s"] == 26400.0 and rec["nr_rmssd"] == 65.0
    assert rec["nr_hr"] == pytest.approx(60000 / 1100)
    assert rec["steps"] == 30  # dos dispositivos: se toma el de más pasos, no la suma (6 + 30)


def test_los_valores_vacios_de_polar_no_cuentan_como_datos(conn):
    d = date(2026, 9, 28)
    store_raw(
        conn,
        source="polar",
        endpoint="nightly-recharge-results",
        day=d,
        body=_nr_doc("2026-09-28", 0, 0),
    )
    store_raw(
        conn, source="polar", endpoint="activity", day=d, body=_act_doc("2026-09-28", ("A", []))
    )
    (rec,) = data.loop_days(conn)
    assert rec["nr_rmssd"] is None and rec["nr_hr"] is None and rec["steps"] is None


def test_home_con_la_loop_usa_la_loop_y_conserva_la_carga_de_intervals(conn):
    seed_days(conn, 30)  # intervals.icu: solo debe aportar la carga
    seed_loop(conn, 10)
    h = data.home(conn, source="loop")
    noche, nervioso, carga = h["dials"]
    assert (noche["origin"], nervioso["origin"], carga["origin"]) == ("POLAR", "POLAR", "INTERVALS")
    assert (nervioso["tag"], carga["tag"]) == ("CALC", "CALC")
    assert noche["signal"] == "loop_sleep" and nervioso["signal"] == "loop_hrv"
    assert [s["key"] for s in h["signals"]] == ["loop_hrv", "loop_hr", "loop_sleep", "ctl"]
    assert {s["key"]: s["origin"] for s in h["signals"]}["ctl"] == "INTERVALS"
    assert h["steps_source"] == "Polar Loop" and h["steps"] == 5 + 9 + 7 and h["source"] == "loop"
    assert h["steps_day"] == "2026-09-29"


def test_la_loop_no_mezcla_datos_del_reloj(conn):
    seed_days(conn, 30)  # solo hay reloj: sueño, VFC y pasos de intervals no deben colarse
    h = data.home(conn, source="loop")
    assert h["dials"][0]["state"] == "sin datos" and h["dials"][1]["state"] == "sin datos"
    assert h["steps"] is None and h["dials"][2]["value"] != "—"  # la carga sí sale de intervals


def test_una_sola_noche_de_la_loop_no_inventa_un_rango(conn):
    seed_loop(conn, 1)
    noche, nervioso, _ = data.home(conn, source="loop")["dials"]
    assert noche["state"].startswith("sin rango") and "1/7" in noche["state"]
    assert noche["value"] != "—" and nervioso["value"] != "—" and noche["band"] is None


def test_con_diez_noches_de_la_loop_ya_hay_rango_y_estado(conn):
    seed_loop(conn, 10)
    noche, nervioso, _ = data.home(conn, source="loop")["dials"]
    assert noche["state"] in {"en rango", "por encima", "por debajo"} and noche["band"] is not None
    assert nervioso["state"] in {"en rango", "por encima", "por debajo"}


def test_detalle_de_una_senal_de_la_loop(conn):
    seed_loop(conn, 10)
    mark_status(conn, source="polar", endpoint="sleeps", ok=True)
    hrv = data.signal_detail(conn, "loop_hrv", 28)
    assert (hrv["origin"], hrv["source_label"], hrv["label"]) == ("POLAR", "Polar Loop", "VFC")
    assert hrv["nature"].startswith("CALC") and "Nightly Recharge" in hrv["nature"]
    assert hrv["updated_min"] is not None and hrv["available_days"] == 10
    sleep = data.signal_detail(conn, "loop_sleep", 28)
    assert sleep["nature"] == "MED · medido por la Loop" and sleep["agg"] == "last"
    assert ":" in sleep["value"] and sleep["value"].endswith(" h")
    hr = data.signal_detail(conn, "loop_hr", 28)
    assert hr["unit"] == "lpm" and hr["range"] is not None


def test_las_senales_del_reloj_siguen_siendo_de_intervals(conn):
    seed_days(conn, 30)
    d = data.signal_detail(conn, "hrv", 28)
    assert (d["origin"], d["source_label"]) == ("INTERVALS", "intervals.icu")


def test_api_usa_la_loop_por_defecto_y_intervals_si_se_configura(conn, settings):
    import dataclasses

    seed_loop(conn, 10)
    seed_days(conn, 30)
    loop_client = TestClient(create_app(lambda: conn, settings))
    assert settings.wellness_source == "loop"
    h = loop_client.get("/api/home").json()
    assert h["source"] == "loop" and h["dials"][0]["origin"] == "POLAR"
    assert loop_client.get("/api/senal/loop_hrv?days=28").status_code == 200
    watch = TestClient(
        create_app(lambda: conn, dataclasses.replace(settings, wellness_source="intervals"))
    )
    h2 = watch.get("/api/home").json()
    assert h2["source"] == "intervals" and h2["dials"][0]["origin"] == "INTERVALS"


def test_wellness_source_se_lee_del_entorno_con_valor_seguro_por_defecto(tmp_path, monkeypatch):
    from ares.config import load_settings

    monkeypatch.setenv("ARES_DATA_DIR", str(tmp_path))
    nada = tmp_path / "no-existe.env"
    monkeypatch.delenv("WELLNESS_SOURCE", raising=False)
    assert load_settings(env_file=nada).wellness_source == "loop"
    monkeypatch.setenv("WELLNESS_SOURCE", "intervals")
    assert load_settings(env_file=nada).wellness_source == "intervals"
    monkeypatch.setenv("WELLNESS_SOURCE", "cualquier-cosa")
    assert load_settings(env_file=nada).wellness_source == "loop"


def test_lab_dice_que_version_del_codigo_corre(conn, settings):
    v = data.lab(conn, settings)["versions"]
    assert isinstance(v["code"], str) and v["code"]
