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


def test_fuentes_frescura_y_solo_las_que_sincronizan(conn):
    mark_status(conn, source="intervals", endpoint="wellness", ok=True)
    mark_status(conn, source="tredict", endpoint="activity", ok=False, error="HTTP 401")
    now = datetime.now(UTC) + timedelta(hours=2)
    by = {s["source"]: s for s in data.sources(conn, now)}
    assert by["intervals"]["level"] == "ok" and by["intervals"]["age_min"] >= 120
    assert by["tredict"]["level"] == "bad" and by["tredict"]["error"] == "HTTP 401"
    assert set(by) == {"intervals", "tredict"}  # sin filas de fuentes que no existen
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
    assert lab["gate"]["level"] == "sin evaluar" and lab["versions"]["schema"] == 5
    page = client.get("/")
    assert page.status_code == 200 and "ARES" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/docs").status_code == 404  # sin documentación pública de la API


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
    assert by["intervals"]["last_ok"] is not None and set(by) == {"intervals"}


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


def test_las_senales_del_reloj_siguen_siendo_de_intervals(conn):
    seed_days(conn, 30)
    d = data.signal_detail(conn, "hrv", 28)
    assert (d["origin"], d["source_label"]) == ("INTERVALS", "intervals.icu")


def test_api_etiqueta_lo_de_intervals_con_la_pulsera_del_proveedor_activo(conn, settings):
    seed_days(conn, 30)
    assert settings.physiology_provider == "whoop"
    h = TestClient(create_app(lambda: conn, settings)).get("/api/home").json()
    assert [d["origin"] for d in h["dials"]] == ["COROS vía INTERVALS"] * 2 + ["INTERVALS"]
    assert "source" not in h  # ya no hay modos de fuente


# ------------------------------- WHOOP conectada a intervals.icu: campos nuevos y etiquetas


def seed_whoop_days(conn, n: int = 14) -> None:
    """Bienestar de intervals.icu con los campos que aparecen al conectar WHOOP (30/09/2026)."""
    for i in range(n):
        d = date(2026, 9, 1) + timedelta(days=i)
        store_raw(
            conn,
            source="intervals",
            endpoint="wellness",
            day=d,
            body={
                "id": d.isoformat(),
                "hrv": 55 + i % 6,
                "restingHR": 52 + i % 4,
                "sleepSecs": 26000 + 200 * i,
                "avgSleepingHR": 55,
                "readiness": 50 + 3 * (i % 10),
                "respiration": 15.0 + 0.1 * (i % 5),
                "spO2": 95 + i % 3,
                "sleepScore": 70 + i % 12,
                "ctl": 30 + i,
                "atl": 35 + i,
                "rampRate": 1.2,
            },
        )


def test_se_leen_los_campos_que_trae_whoop_por_intervals(conn):
    seed_whoop_days(conn, 5)
    last = data.intervals_days(conn)[-1]
    assert last["readiness"] == 62 and last["spO2"] == 96 and last["sleepScore"] == 74
    assert last["respiration"] == pytest.approx(15.4)


def test_con_pulsera_declarada_las_senales_incluyen_recovery_spo2_y_respiracion(conn):
    seed_whoop_days(conn, 14)
    h = data.home(conn, device="whoop")
    assert [s["key"] for s in h["signals"]] == [
        "recovery",
        "hrv",
        "rhr",
        "sleep",
        "spo2",
        "resp",
        "ctl",
    ]
    origin = {s["key"]: s["origin"] for s in h["signals"]}
    assert origin["recovery"] == origin["hrv"] == "WHOOP vía INTERVALS"
    assert origin["ctl"] == "INTERVALS"
    assert [d["origin"] for d in h["dials"]] == ["WHOOP vía INTERVALS"] * 2 + ["INTERVALS"]
    rec = next(s for s in h["signals"] if s["key"] == "recovery")
    assert rec["tag"] == "CALC" and rec["value"] == "59 %"  # último día: 50 + 3·(13 % 10)


def test_sin_pulsera_declarada_todo_sigue_siendo_de_intervals(conn):
    seed_whoop_days(conn, 14)
    h = data.home(conn)
    assert [s["key"] for s in h["signals"]] == ["hrv", "rhr", "sleep", "sleep_hr", "ctl"]
    assert {s["origin"] for s in h["signals"]} == {"INTERVALS"}


def test_detalle_de_recovery_y_spo2_dice_quien_lo_mide_y_quien_lo_calcula(conn):
    seed_whoop_days(conn, 14)
    rec = data.signal_detail(conn, "recovery", 28, device="WHOOP")
    assert rec["origin"] == rec["source_label"] == "WHOOP vía INTERVALS"
    assert rec["nature"] == "CALC · calculado por WHOOP y transmitido por intervals.icu"
    assert rec["unit"] == "%" and rec["tag"] == "CALC"
    spo2 = data.signal_detail(conn, "spo2", 28, device="WHOOP")
    assert spo2["nature"] == "MED · medido por WHOOP; intervals.icu solo lo transmite"
    ctl = data.signal_detail(conn, "ctl", 28, device="WHOOP")  # la carga no es de la pulsera
    assert (ctl["origin"], ctl["source_label"]) == ("INTERVALS", "intervals.icu")


def test_cambiar_de_pulsera_solo_cambia_la_etiqueta(conn):
    seed_whoop_days(conn, 14)
    oura = data.signal_detail(conn, "hrv", 28, device="Oura")
    assert oura["origin"] == oura["source_label"] == "OURA vía INTERVALS"


def test_api_sirve_las_senales_nuevas(conn, settings):
    seed_whoop_days(conn, 14)
    client = TestClient(create_app(lambda: conn, settings))
    for key in ("recovery", "spo2", "resp", "sleep_score"):
        r = client.get(f"/api/senal/{key}?days=28")
        assert r.status_code == 200 and r.json()["origin"] == "COROS vía INTERVALS", key


def test_lab_dice_que_version_del_codigo_corre(conn, settings):
    v = data.lab(conn, settings)["versions"]
    assert isinstance(v["code"], str) and v["code"]
    assert v["algo"] == "whoop-1" and "filter" not in v
