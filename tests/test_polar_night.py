"""El análisis de la noche recupera lo que se sabe de una noche sintética: se construye con
un rMSSD conocido por segmento (alternando dos intervalos, la diferencia sucesiva es la
amplitud) y con la misma convención que Polar (offsets desde la medianoche local)."""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ares import polar_night as pn

TZ = ZoneInfo("Europe/Madrid")
DAY = date(2026, 9, 30)
PREV = date(2026, 9, 29)


def local_ms(y, m, d, hh=0, mm=0) -> int:
    return int(datetime(y, m, d, hh, mm, tzinfo=TZ).astimezone(UTC).timestamp() * 1000)


def build_night(seed: int = 5, marca: str = "fin"):
    """Latidos de 22:30 a 07:30 con amplitud (rMSSD) constante en cada bloque de 5 min."""
    random.seed(seed)
    t0 = local_ms(2026, 9, 29, 22, 30)
    t_end = local_ms(2026, 9, 30, 7, 30)
    n_seg = (t_end - t0) // pn.SEG_MS
    amps = [random.uniform(12, 45) for _ in range(n_seg + 1)]
    mid = local_ms(2026, 9, 30)
    prev_s, day_s, t, flip = [], [], t0, False
    while t < t_end:
        a = amps[(t - t0) // pn.SEG_MS]
        flip = not flip
        pp = int(round(900 + (a if flip else 0)))
        if marca == "fin":
            t += pp  # el desplazamiento marca el final del intervalo
        sample = {
            "offsetMillis": 0,
            "ppInterval": pp,
            "errorEstimateMillis": 5,
            "skinContact": True,
            "movement": False,
            "offline": False,
        }
        if t < mid:
            prev_s.append({**sample, "offsetMillis": t - local_ms(2026, 9, 29)})
        else:
            day_s.append({**sample, "offsetMillis": t - mid})
        if marca == "inicio":
            t += pp  # el desplazamiento marca el inicio (lo que devuelve la Loop de verdad)
    return amps, prev_s, day_s


def ppi_doc(day: date, samples: list[dict]) -> dict:
    return {
        "dailyPpiSamples": [
            {
                "date": day.isoformat(),
                "modified": "2026-09-30T04:00:00Z",
                "ppiSamplesPerDevice": [{"recordingDevice": {"uuid": "d"}, "ppiSamples": samples}],
            }
        ]
    }


def write(root: Path, dirname: str, name: str, doc: dict) -> None:
    (root / dirname).mkdir(parents=True, exist_ok=True)
    (root / dirname / name).write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture(params=["fin", "inicio"])
def night(tmp_path: Path, request):
    amps, prev_s, day_s = build_night(marca=request.param)
    write(tmp_path, "20260930T035709Z", "ppi_samples__dia.json", ppi_doc(PREV, prev_s))
    write(tmp_path, "20260930T035711Z", "ppi_samples__dia.json", ppi_doc(DAY, day_s))
    write(
        tmp_path,
        "20260930T035711Z",
        "sleeps__dia.json",
        {
            "nightSleeps": [
                {
                    "sleepDate": "2026-09-30",
                    "sleepResult": {
                        "hypnogram": {
                            "sleepStart": "2026-09-29T23:00:00.000+02:00",
                            "sleepEnd": "2026-09-30T07:00:00.000+02:00",
                            "batteryRanOut": False,
                        }
                    },
                }
            ]
        },
    )
    # Nightly Recharge empieza 30 min después de dormirse (23:30 local, sin zona): bloque 12
    write(
        tmp_path,
        "20260930T035711Z",
        "nightly_recharge__dia.json",
        {
            "nightlyRechargeResults": [
                {
                    "sleepResultDate": "2026-09-30",
                    "meanNightlyRecoveryRmssd": 30,
                    "hrvSamples": [
                        {
                            "startTime": "2026-09-29T23:30:00",
                            "sampleInterval": "300s",
                            "hrvValues": amps[12 : 12 + 90],
                        }
                    ],
                }
            ]
        },
    )
    return tmp_path, amps


def test_la_medianoche_local_es_el_origen_de_los_desplazamientos():
    # Madrid en septiembre es UTC+2: las 00:00 locales son las 22:00 UTC del día anterior
    expected = int(datetime(2026, 9, 29, 22, 0, tzinfo=UTC).timestamp() * 1000)
    assert pn.day_start_ms(DAY, TZ) == expected


def test_recupera_el_rmssd_conocido_y_la_semantica_del_desplazamiento(night):
    root, amps = night
    rep = pn.night_report(root, DAY, TZ)
    assert rep["mode"] in {"fin", "inicio"} and rep["mode_resid_ms"] < 5
    assert rep["docs"]["2026-09-29"] > 0 and rep["docs"]["2026-09-30"] > 0
    v = rep["variants"]["filtro v0.3 (todas las reglas)"]
    assert v["segments_ok"] == 48 and v["n_seg"] == 48
    # ventana: 23:30 → 03:30, bloques 12..59 de la construcción
    truth = sorted(amps[12:60])[len(amps[12:60]) // 2 - 1 : len(amps[12:60]) // 2 + 1]
    expected = sum(truth) / 2
    assert v["rmssd_ms"] == pytest.approx(expected, rel=0.03)
    assert rep["night"]["coverage_pct"] == pytest.approx(100, abs=2)
    assert rep["night"]["movement_pct"] == 0
    assert rep["junction_s"] is not None and rep["junction_s"] < 2.0


def test_compara_con_nightly_recharge_y_prefiere_la_alineacion_local(night):
    root, _ = night
    nr = pn.night_report(root, DAY, TZ)["nr"]
    loc = nr["alignments"]["local"]["filtro v0.3 (todas las reglas)"]
    utc = nr["alignments"]["utc"]["filtro v0.3 (todas las reglas)"]
    assert loc["n"] >= 80 and loc["r"] > 0.99 and abs(loc["bias_ln"]) < 0.03
    assert utc["r"] is None or utc["r"] < 0.6  # desalineada 2 h: no debe coincidir


def test_flags_marcan_cada_artefacto():
    beats = [
        pn.Beat(1000, 900, 5, True, False),  # normal
        pn.Beat(1900, 905, 5, True, True),  # movimiento
        pn.Beat(2800, 900, 50, True, False),  # error grande
        pn.Beat(3050, 250, 5, True, False),  # fuera de rango (y salto)
        pn.Beat(3950, 900, 5, False, False),  # sin contacto (y salto respecto al anterior)
    ]
    fl = pn.flags(beats)
    assert fl[0] == frozenset()
    assert fl[1] == {"movimiento"} and fl[2] == {"error"}
    assert {"rango", "salto"} <= fl[3] and {"contacto", "salto"} <= fl[4]


def test_una_serie_constante_da_rmssd_cero_y_no_se_inventa_nada():
    beats, t = [], 0
    for _ in range(400):
        t += 900
        beats.append(pn.Beat(t, 900, 5, True, False))
    fl = pn.flags(beats)
    mode, _ = pn.detect_mode(beats)
    segs = pn.seg_rmssd(pn.valid_diffs(beats, fl, frozenset(), mode), 0, 1, 400_000, min_diffs=30)
    assert segs == [0.0]


def test_un_hueco_grande_corta_la_continuidad():
    beats = [pn.Beat(900 * (i + 1), 900, 5, True, False) for i in range(60)]
    beats += [pn.Beat(900 * 61 + 5000 + 900 * (i + 1), 900, 5, True, False) for i in range(60)]
    mode, _ = pn.detect_mode(beats)
    diffs = pn.valid_diffs(beats, pn.flags(beats), frozenset(), mode)
    assert len(diffs) == 59 + 59  # el par que cruza el hueco no cuenta


def test_faltan_los_ficheros_y_el_mensaje_dice_que_hacer(tmp_path: Path):
    with pytest.raises(pn.NightError, match="polar-probe"):
        pn.night_report(tmp_path, DAY, TZ)


def test_se_usa_la_sonda_mas_reciente_que_contenga_el_dia(night):
    root, _ = night
    write(
        root, "20260930T050000Z", "ppi_samples__dia.json", ppi_doc(DAY, [])
    )  # más nueva pero vacía
    assert pn.night_report(root, DAY, TZ)["docs"]["2026-09-30"] > 0


def test_el_informe_es_texto_agregado_sin_latidos_sueltos(night):
    root, _ = night
    text = pn.render(pn.night_report(root, DAY, TZ))
    for frag in (
        "Toda la noche",
        "Ventana de cálculo",
        "rMSSD según qué reglas",
        "Nightly Recharge",
        "alineación local",
        "alineación utc",
    ):
        assert frag in text
    assert "23:00 → 07:00" in text


@pytest.mark.parametrize("marca", ["fin", "inicio"])
def test_detecta_si_el_desplazamiento_marca_el_inicio_o_el_final(marca):
    _, prev_s, day_s = build_night(marca=marca)
    beats = pn.beats_from_doc(ppi_doc(DAY, day_s), DAY, TZ)
    mode, resid = pn.detect_mode(beats)
    assert mode == marca and resid < 5
