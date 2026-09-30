"""Sonda de Polar: la descripción de estructura no filtra valores, y las llamadas
usan `from` inclusivo / `to` exclusivo y `features` como indica la documentación."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from ares.connectors import polar_probe as probe

# Respuestas de ejemplo de la documentación oficial de la API v4 (datos de muestra).
PPI = {
    "dailyPpiSamples": [
        {
            "date": "2025-08-01",
            "modified": "2025-08-01T12:00:00Z",
            "ppiSamplesPerDevice": [
                {
                    "recordingDevice": {"uuid": "0e030000-0084-0000-0000-00001234abcd"},
                    "ppiSamples": [
                        {
                            "offsetMillis": 70,
                            "ppInterval": 1052,
                            "errorEstimateMillis": 10,
                            "skinContact": True,
                            "movement": False,
                            "offline": False,
                        },
                        {
                            "offsetMillis": 1120,
                            "ppInterval": 1050,
                            "errorEstimateMillis": 12,
                            "skinContact": True,
                            "movement": True,
                            "offline": False,
                        },
                    ],
                    "recordingTriggerTypeChanges": [
                        {"triggerType": "TRIGGER_TYPE_UNDEFINED", "offsetMillis": 70}
                    ],
                }
            ],
        }
    ]
}
SLEEPS = {
    "nightSleeps": [
        {
            "sleepDate": "2025-01-02",
            "sleepResult": {
                "hypnogram": {
                    "sleepStart": "2025-01-01T23:12:33.435+02:00",
                    "sleepEnd": "2025-01-02T08:12:33.435+02:00",
                    "sleepGoal": "28800s",
                    "batteryRanOut": True,
                    "deviceReference": {"uuid": "0e030000-0084-0000-0000-00001234abcd"},
                    "sleepStateChanges": [
                        {"offsetFromStart": "30s", "newState": "SLEEP_STATE_WAKE"}
                    ],
                }
            },
        }
    ]
}


def test_estructura_no_revela_valores_ni_identificadores():
    text = "\n".join(probe.shape_of(PPI))
    assert "0e030000" not in text  # el uuid del dispositivo no aparece
    assert "recordingDevice" in text and "uuid: str(len=36)" in text
    assert "ppInterval: int" in text  # el valor suelto no aparece, solo el tipo
    assert "ppInterval: rango [1050 .. 1052]" in text
    assert "offsetMillis: rango [70 .. 1120]" in text
    assert "movement: true=1 false=1" in text
    assert "modified: fecha/hora NNNN-NN-NNTNN:NN:NN zona=Z" in text
    assert "date: fecha 2025-08-01" in text  # las fechas sueltas sí: dicen qué días hay datos


def test_sueno_muestra_la_zona_horaria_sin_los_valores_de_hora():
    text = "\n".join(probe.shape_of(SLEEPS))
    assert "sleepStart: fecha/hora NNNN-NN-NNTNN:NN:NN.NNN zona=+02:00" in text
    assert "23:12" not in text
    assert "sleepGoal: duración NNNNNs" in text
    assert "newState: enum SLEEP_STATE_WAKE" in text
    assert "batteryRanOut: bool" in text


def test_lista_vacia_y_nulos():
    text = "\n".join(probe.shape_of({"a": [], "b": None}))
    assert "a: lista vacía" in text and "b: null" in text


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llamadas_usan_to_exclusivo_features_y_bearer(tmp_path: Path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=PPI if "ppi" in request.url.path else {})

    results = probe.run_probe("tok", date(2026, 9, 29), tmp_path, make_client(handler))

    ppi_day = next(
        r for r in seen if r.url.path.endswith("/ppi-samples") and "features" in r.url.params
    )
    assert ppi_day.url.params["from"] == "2026-09-29"
    assert ppi_day.url.params["to"] == "2026-09-30"  # exclusivo: el día siguiente
    assert ppi_day.url.params["features"] == "samples"
    assert ppi_day.headers["Authorization"] == "Bearer tok"

    plain = next(
        r for r in seen if r.url.path.endswith("/ppi-samples") and "features" not in r.url.params
    )
    assert plain.url.params["from"] == "2026-09-23"  # 7 días que terminan el día 29
    assert plain.url.params["to"] == "2026-09-30"

    assert len(results) == 8 + 5  # 8 sin features + 5 endpoints con features
    saved = tmp_path / "ppi_samples__dia.json"
    assert json.loads(saved.read_text())["dailyPpiSamples"][0]["date"] == "2025-08-01"


def test_features_multiples_prueban_coma_si_la_clave_repetida_da_400(tmp_path: Path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sleeps") and "features" in request.url.params:
            calls.append(str(request.url.query))
            # Solo acepta la lista separada por comas
            if "," not in request.url.params["features"]:
                return httpx.Response(400, json={"error": "bad"})
            return httpx.Response(200, json=SLEEPS)
        return httpx.Response(200, json={})

    results = probe.run_probe("tok", date(2026, 9, 29), tmp_path, make_client(handler))
    sleeps_day = next(r for r in results if r.name == "sleeps" and r.variant == "dia")
    assert sleeps_day.status == 200
    assert "comas" in sleeps_day.note
    assert len(calls) == 2  # primero clave repetida, luego comas


def test_error_http_se_informa_sin_romper_la_sonda(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/temperature-measurements"):
            return httpx.Response(403, json={"message": "scope missing"})
        return httpx.Response(200, json={})

    results = probe.run_probe("tok", date(2026, 9, 29), tmp_path, make_client(handler))
    temp = next(r for r in results if r.name == "temperature")
    assert temp.status == 403 and "403" in temp.note and temp.saved is None
    assert sum(1 for r in results if r.status == 200) == 12


def test_render_incluye_resumen_y_carpeta(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PPI)

    results = probe.run_probe("tok", date(2026, 9, 29), tmp_path, make_client(handler))
    out = probe.render(results, tmp_path)
    assert "13/13 llamadas correctas" in out
    assert str(tmp_path) in out


def test_una_fecha_de_nacimiento_no_se_muestra():
    """Regresión: la sonda enseñó `birthday` tal cual en la primera noche real."""
    body = {
        "nightSleeps": [
            {
                "sleepDate": "2026-09-30",
                "birthday": "1990-11-11",
                "deviceReference": {"uuid": "0e030000-0084-0000-0000-00001234abcd"},
            }
        ]
    }
    text = "\n".join(probe.shape_of(body))
    assert "1990" not in text and "11-11" not in text
    assert "birthday: fecha NNNN-NN-NN" in text
    assert "sleepDate: fecha 2026-09-30" in text  # los días con datos sí se ven
