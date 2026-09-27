"""Contrato del conector de intervals.icu con respuesta simulada.

En la semana 1 se sustituye la fixture por una respuesta real grabada y anonimizada.
"""

from __future__ import annotations

import base64
import json
from datetime import date

import httpx

from ares.connectors.base import HttpClient
from ares.connectors.intervals import sync_wellness

FIXTURE = [
    {
        "id": "2026-09-25",
        "ctl": 57.1,
        "atl": 61.8,
        "restingHR": 47,
        "hrv": 58.0,
        "sleepSecs": 26640,
        "sleepScore": 82,
    },
    {
        "id": "2026-09-26",
        "ctl": 57.6,
        "atl": 63.9,
        "restingHR": 46,
        "hrv": 61.0,
        "sleepSecs": 27480,
        "sleepScore": 85,
    },
    {
        "id": "2026-09-27",
        "ctl": 57.4,
        "atl": 60.2,
        "restingHR": 46,
        "hrv": 62.0,
        "sleepSecs": 27480,
        "sleepScore": 86,
    },
]


def make_http(payload, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    return HttpClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def test_peticion_correcta_y_guardado_en_capa_bruta(conn):
    seen: list[httpx.Request] = []
    res = sync_wellness(
        conn, make_http(FIXTURE, seen), "clave-falsa", "0", days=3, today=date(2026, 9, 27)
    )
    assert (res.fetched, res.inserted) == (3, 3)

    req = seen[0]
    assert req.url.path == "/api/v1/athlete/0/wellness"
    assert req.url.params["oldest"] == "2026-09-25"
    assert req.url.params["newest"] == "2026-09-27"
    expected_auth = "Basic " + base64.b64encode(b"API_KEY:clave-falsa").decode()
    assert req.headers["Authorization"] == expected_auth

    rows = conn.execute("SELECT day, body FROM raw_intervals_wellness ORDER BY day").fetchall()
    assert [r[0] for r in rows] == [date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27)]
    assert json.loads(rows[2][1])["restingHR"] == 46

    status = conn.execute(
        "SELECT device_id, last_ok IS NOT NULL FROM source_status "
        "WHERE source='intervals' AND endpoint='wellness'"
    ).fetchone()
    assert status == ("global", True)
