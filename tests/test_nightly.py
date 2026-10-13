"""Noches de WHOOP → daily_metrics (Implementation Plan v0.3, §6 y §10).

VFC sin épsilon, una prueba por fila de la tabla de calidad, siestas, noches que cruzan
medianoche, la noche del cambio de hora (24 al 25 de octubre de 2026), pasos como segunda
fuente, versiones de un mismo registro, contrato Physiology Provider e idempotencia."""

from __future__ import annotations

import math
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from whoop_synthetic import cycle, merge, night, recovery, sleep, utc

from ares import db
from ares.connectors import whoop
from ares.connectors.base import store_raw
from ares.metrics import nightly
from ares.provider import NormalizedNight

MADRID = ZoneInfo("Europe/Madrid")
DEVICE = "pulsera-principal"


def load(conn, data) -> None:
    for endpoint, records in data.items():
        for rec in records:
            store_raw(
                conn,
                source="whoop",
                endpoint=endpoint,
                day=whoop.raw_day(endpoint, rec, MADRID),
                body=rec,
                device_id=DEVICE,
            )


def nights_of(conn, data) -> list[NormalizedNight]:
    load(conn, data)
    return whoop.WhoopAdapter(MADRID).nights(conn, DEVICE)


def one(conn, data) -> NormalizedNight:
    (n,) = nights_of(conn, data)
    return n


def rebuild(conn, since=None) -> int:
    return nightly.rebuild(
        conn, whoop.WhoopAdapter(MADRID), device_id=DEVICE, algo_version="whoop-1", since=since
    )


# --------------------------------------------------------------------------------- VFC


def test_rmssd_valido_da_su_logaritmo():
    assert nightly.compute_ln_rmssd(58.2) == pytest.approx(math.log(58.2))


@pytest.mark.parametrize("value", [None, 0.0, -3.0, float("nan"), float("inf"), 4.99, 300.01])
def test_ausente_cero_o_implausible_invalida_la_noche_sin_epsilon(value):
    assert nightly.compute_ln_rmssd(value) is None


def test_los_limites_de_plausibilidad_son_inclusivos():
    assert nightly.compute_ln_rmssd(5.0) == pytest.approx(math.log(5.0))
    assert nightly.compute_ln_rmssd(300.0) == pytest.approx(math.log(300.0))


@given(st.floats(min_value=5.0, max_value=300.0))
def test_ln_rmssd_es_exactamente_el_logaritmo(x):
    ln = nightly.compute_ln_rmssd(x)
    assert ln is not None and math.exp(ln) == pytest.approx(x)


# ------------------------------------------------------------------- calidad (tabla)


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({}, "high"),  # puntuada, sin calibración, ≥ 6 h, rMSSD plausible
        ({"hours": 5.0}, "fair"),  # 4–6 h
        ({"hours": 4.0}, "fair"),  # 4 h justas
        ({"hours": 6.0}, "high"),  # 6 h justas
        ({"hours": 3.9}, "excluded"),  # < 4 h
        ({"state": "PENDING_SCORE"}, "excluded"),  # puntuación pendiente
        ({"state": "UNSCORABLE"}, "excluded"),  # no puntuable
        ({"calibrating": True}, "excluded"),  # calibración
        ({"rmssd": 412.0}, "excluded"),  # implausible
        ({"rmssd": 0.0}, "excluded"),  # cero
    ],
)
def test_una_prueba_por_fila_de_la_tabla_de_calidad(conn, kw, expected):
    assert nightly.quality(one(conn, merge(night(1, "2026-09-10", **kw)))) == expected


def test_sueno_sin_puntuar_con_recuperacion_puntuada_queda_excluido(conn):
    data = merge(night(1, "2026-09-10"))
    data["sleep"][0]["score_state"] = "PENDING_SCORE"
    del data["sleep"][0]["score"]
    n = one(conn, data)
    assert n.score_state == "PENDING_SCORE" and n.sleep_min is None
    assert nightly.quality(n) == "excluded"


# ------------------------------------------------------------------------- siestas


def _nap(n: int, cycle_id: int, start: str, hours: float) -> dict:
    s = utc(start)
    return sleep(
        n,
        cycle_id,
        s,
        s + timedelta(hours=hours),
        nap=True,
        light_h=hours * 0.6,
        sws_h=hours * 0.2,
        rem_h=hours * 0.2,
    )


def test_una_siesta_nunca_sustituye_a_la_noche_principal(conn):
    data = merge(night(1, "2026-09-10"))
    data["sleep"].append(_nap(2, 1, "2026-09-10T13:00", 1.0))
    n = one(conn, data)
    assert n.provider_sleep_id == data["sleep"][0]["id"] and not n.is_nap
    assert n.night_check == "ok"


def test_si_la_recuperacion_apunta_a_una_siesta_la_noche_se_excluye_y_se_marca(conn):
    data = merge(night(1, "2026-09-10"))
    data["sleep"].append(_nap(2, 1, "2026-09-10T13:00", 1.0))
    data["recovery"][0]["sleep_id"] = data["sleep"][1]["id"]
    n = one(conn, data)
    assert n.is_nap and n.night_check.startswith("siesta")
    assert nightly.quality(n) == "excluded"


def test_se_usa_el_sueno_de_la_recuperacion_y_se_marca_si_no_es_el_mas_largo(conn):
    data = merge(night(1, "2026-09-10", hours=5.0))
    longer = sleep(3, 1, utc("2026-09-10T13:00"), utc("2026-09-10T21:00"))  # 8 h, no siesta
    data["sleep"].append(longer)
    n = one(conn, data)
    assert n.provider_sleep_id == data["sleep"][0]["id"]  # decide recovery.sleep_id
    assert n.night_check == "difiere_del_mas_largo"


def test_recuperacion_sin_su_sueno_no_inventa_una_noche(conn):
    data = merge(night(1, "2026-09-10"))
    data["sleep"] = []
    adapter = whoop.WhoopAdapter(MADRID)
    load(conn, data)
    assert adapter.nights(conn, DEVICE) == [] and adapter.dropped


# ---------------------------------------------------------------------------- tiempo


def test_la_fecha_sale_del_final_en_madrid_aunque_el_utc_sea_de_la_vispera(conn):
    # termina a las 23:30 UTC del 6 de octubre = 01:30 del 7 en Madrid
    n = one(conn, merge(night(1, "2026-10-06", end_time="23:30", hours=2.0)))
    assert n.sleep_end.date() == date(2026, 10, 6)
    assert n.local_sleep_date == date(2026, 10, 7)


def test_noche_que_cruza_medianoche_es_del_dia_en_que_termina(conn):
    n = one(conn, merge(night(1, "2026-10-06")))  # 22:06 UTC del 5 → 05:30 UTC del 6
    assert n.sleep_start.date() == date(2026, 10, 5)
    assert n.local_sleep_date == date(2026, 10, 6)
    assert n.source_tz == "+02:00" and n.night_check == "ok"


@pytest.mark.parametrize("offset", ["+02:00", "+01:00"])
def test_noche_del_cambio_de_hora_del_24_al_25_de_octubre(conn, offset):
    # se duerme a las 23:30 CEST (21:30 UTC) y despierta a las 07:45 CET (06:45 UTC)
    start, end = utc("2026-10-24T21:30"), utc("2026-10-25T06:45")
    data = {
        "cycle": [cycle(1, start, None, tz=offset)],
        "sleep": [sleep(1, 1, start, end, tz=offset)],
        "recovery": [recovery(1, 1, end + timedelta(minutes=5))],
        "workout": [],
    }
    n = one(conn, data)
    assert n.local_sleep_date == date(2026, 10, 25)
    assert n.source_tz == offset  # se conserva el offset de origen
    assert n.night_check == "ok"  # los dos offsets de esa noche son coherentes
    assert n.sleep_end - n.sleep_start == timedelta(hours=9, minutes=15)


def test_de_viaje_el_offset_se_marca_pero_la_fecha_sigue_siendo_de_madrid(conn):
    n = one(conn, merge(night(1, "2026-09-10", end_time="11:00", tz="-05:00")))
    assert n.local_sleep_date == date(2026, 9, 10)
    assert n.night_check == "offset_incoherente" and n.source_tz == "-05:00"


def test_offset_z_y_offset_ilegible():
    s = whoop.Sleep.model_validate(
        sleep(1, 1, utc("2026-01-10T00:00"), utc("2026-01-10T07:00"), tz="Z")
    )
    assert not whoop.offset_matches(s, MADRID)  # en enero Madrid es +01:00
    assert whoop.offset_matches(s, ZoneInfo("UTC"))
    s2 = whoop.Sleep.model_validate(
        sleep(1, 1, utc("2026-01-10T00:00"), utc("2026-01-10T07:00"), tz="raro")
    )
    assert not whoop.offset_matches(s2, MADRID)


# ------------------------------------------------------------------- sueño y valores


def test_sleep_min_es_ligero_mas_profundo_mas_rem(conn):
    n = one(conn, merge(night(1, "2026-09-10")))
    assert n.sleep_min == 420  # 3,5 h + 1,5 h + 2 h; ni despierto ni sin datos
    assert (n.rmssd_ms, n.rhr, n.provider_recovery) == (58.2, 47.0, 71.0)
    assert (n.resp_rate, n.spo2, n.skin_temp) == (14.6, 96.4, 33.7)
    assert n.calibrating is False and n.adapter_version == whoop.ADAPTER_VERSION


def test_spo2_y_temperatura_son_opcionales(conn):
    n = one(conn, merge(night(1, "2026-09-10", spo2=None, skin=None)))
    assert n.spo2 is None and n.skin_temp is None and nightly.quality(n) == "high"


def test_se_usa_la_ultima_version_de_cada_registro(conn):
    load(conn, merge(night(1, "2026-09-10", state="PENDING_SCORE")))
    later = merge(night(1, "2026-09-10", rmssd=61.0))
    later["recovery"][0]["updated_at"] = "2026-09-10T10:00:00.000Z"
    n = one(conn, later)
    assert n.score_state == "SCORED" and n.rmssd_ms == 61.0


def test_un_cuerpo_que_no_cumple_el_contrato_se_ignora_y_se_cuenta(conn):
    data = merge(night(1, "2026-09-10"))
    bad = dict(data["recovery"][0])
    del bad["sleep_id"]
    bad["cycle_id"] = 99
    data["recovery"].append(bad)
    adapter = whoop.WhoopAdapter(MADRID)
    load(conn, data)
    assert len(adapter.nights(conn, DEVICE)) == 1 and adapter.invalid["recovery"] == 1


def test_dos_noches_el_mismo_dia_local_se_queda_la_no_siesta_mas_larga(conn):
    a = merge(night(1, "2026-09-10", hours=7.0))
    b = merge(night(2, "2026-09-10", hours=3.0, end_time="10:30"))
    adapter = whoop.WhoopAdapter(MADRID)
    load(conn, merge(a, b))
    (n,) = adapter.nights(conn, DEVICE)
    assert n.provider_cycle_id == 1 and len(adapter.dropped) == 1


# ---------------------------------------------------------------------------- pasos


def test_los_pasos_del_ciclo_se_guardan_aparte_y_pueden_ser_nulos(conn):
    load(conn, merge(night(1, "2026-09-10", steps=9100), night(2, "2026-09-11", steps=None)))
    rebuild(conn)
    rows = conn.execute(
        "SELECT local_sleep_date, steps_whoop_cycle FROM daily_metrics ORDER BY 1"
    ).fetchall()
    assert rows == [(date(2026, 9, 10), 9100), (date(2026, 9, 11), None)]


def test_apple_y_whoop_nunca_se_suman_la_discrepancia_se_registra():
    chk = nightly.steps_concordance(10_000, 9_100)
    assert (chk.apple_day, chk.whoop_cycle, chk.diff) == (10_000, 9_100, -900)
    assert chk.rel_diff == pytest.approx(-0.09)
    assert 19_100 not in vars(chk).values()
    assert nightly.steps_concordance(None, 9_100).diff is None
    assert nightly.steps_concordance(10_000, None).diff is None
    assert nightly.steps_concordance(0, 50).rel_diff is None


# ------------------------------------------------------------------- daily_metrics


def test_rebuild_escribe_la_fila_completa_con_procedencia_y_versiones(conn):
    load(conn, merge(night(1, "2026-09-10")))
    conn.execute(
        "INSERT INTO raw_payload VALUES ('intervals','wellness', DATE '2026-09-10', NULL, now(), "
        '\'h1\', \'{"id": "2026-09-10", "ctl": 57.1, "atl": 61.8}\')'
    )
    assert rebuild(conn) == 1
    row = conn.execute(
        "SELECT quality, ln_rmssd, hrv_tag, hrv_origin, algo_version, adapter_version, ctl, atl, "
        "whoop_sleep_id, whoop_cycle_id, night_check, sleep_min, device_id FROM daily_metrics"
    ).fetchone()
    assert row[0] == "high" and row[1] == pytest.approx(math.log(58.2))
    assert row[2:6] == ("MED", "WHOOP", "whoop-1", whoop.ADAPTER_VERSION)
    assert row[6:8] == (57.1, 61.8)
    assert row[9:] == (1, "ok", 420, DEVICE)


def test_la_noche_excluida_se_guarda_con_su_valor_pero_sin_ln(conn):
    load(conn, merge(night(1, "2026-09-10", rmssd=412.0)))
    rebuild(conn)
    row = conn.execute("SELECT rmssd_ms, ln_rmssd, quality FROM daily_metrics").fetchone()
    assert row == (412.0, None, "excluded")


def test_ejecutar_dos_veces_deja_la_base_identica(conn):
    load(conn, merge(*[night(i, f"2026-09-{10 + i:02d}") for i in range(10)]))
    rebuild(conn)
    first = db.fingerprint(conn, ["daily_metrics", "raw_payload", "devices"])
    rebuild(conn)
    rebuild(conn, since=date(2026, 9, 15))
    assert db.fingerprint(conn, ["daily_metrics", "raw_payload", "devices"]) == first


def test_since_solo_reescribe_la_ventana(conn):
    load(conn, merge(*[night(i, f"2026-09-{10 + i:02d}") for i in range(5)]))
    rebuild(conn)
    conn.execute(
        "UPDATE daily_metrics SET night_check = 'marca' WHERE local_sleep_date < '2026-09-13'"
    )
    assert rebuild(conn, since=date(2026, 9, 13)) == 2
    marks = conn.execute(
        "SELECT count(*) FROM daily_metrics WHERE night_check = 'marca'"
    ).fetchone()[0]
    assert marks == 3


def test_otro_dispositivo_no_se_toca(conn):
    load(conn, merge(night(1, "2026-09-10")))
    conn.execute(
        "INSERT INTO daily_metrics (local_sleep_date, device_id, quality) "
        "VALUES (DATE '2026-09-10', 'otra-pulsera', 'high')"
    )
    rebuild(conn)
    assert conn.execute("SELECT count(*) FROM daily_metrics").fetchone()[0] == 2


# --------------------------------------------------------- contrato Physiology Provider


class FakeProvider:
    """Un adaptador de prueba que entrega noches ya normalizadas, sin saber de WHOOP."""

    name = "prueba"
    adapter_version = "prueba-1"

    def __init__(self, nights: list[NormalizedNight]) -> None:
        self._nights = nights

    def nights(self, conn, device_id: str) -> list[NormalizedNight]:
        return [n for n in self._nights if n.device_id == device_id]


def test_un_adaptador_de_prueba_produce_las_mismas_noches_normalizadas(conn, settings):
    data = merge(*[night(i, f"2026-10-{20 + i:02d}") for i in range(7)])
    expected = nights_of(conn, data)
    rebuild(conn)
    via_whoop = db.fingerprint(conn, ["daily_metrics"])

    other = db.connect(settings.data_dir / "otra.duckdb")
    db.migrate(other, settings.migrations_dir)
    nightly.rebuild(other, FakeProvider(expected), device_id=DEVICE, algo_version="whoop-1")
    assert db.fingerprint(other, ["daily_metrics"]) == via_whoop
    other.close()


def test_el_motor_rechaza_dos_noches_para_el_mismo_dia(conn):
    n = one(conn, merge(night(1, "2026-09-10")))
    with pytest.raises(ValueError, match="mismo día"):
        nightly.rebuild(conn, FakeProvider([n, n]), device_id=DEVICE, algo_version="whoop-1")


def test_el_contrato_exige_instantes_con_zona():
    with pytest.raises(ValueError):
        NormalizedNight(
            local_sleep_date=date(2026, 9, 10),
            sleep_start=utc("2026-09-09T22:00").replace(tzinfo=None),
            sleep_end=utc("2026-09-10T06:00"),
            source_tz=None,
            sleep_min=420,
            rmssd_ms=50.0,
            rhr=48.0,
            score_state="SCORED",
            calibrating=False,
            device_id=DEVICE,
            adapter_version="x",
        )
