"""Contrato del conector de Tredict con respuestas simuladas, según la documentación oficial
(https://www.tredict.com/blog/oauth_docs/, verificada el 27/09/2026): paginación por
`_links.next.href` y `Authorization: Bearer`.
"""

from __future__ import annotations

import json
from datetime import date

import httpx

from ares.connectors.base import HttpClient
from ares.connectors.tredict import BASE_URL, sync_activities

PAGE_1 = {
    "_links": {
        "self": {"href": f"{BASE_URL}/activityList?pageSize=2"},
        "next": {"href": f"{BASE_URL}/activityList?startDate=2026-09-25T06:00:00.000Z&pageSize=2"},
    },
    "count": 2,
    "_embedded": {
        "activityList": [
            {"id": "act-27", "date": "2026-09-27T06:12:00.000Z", "sportType": "running"},
            {"id": "act-26", "date": "2026-09-26T06:05:00.000Z", "sportType": "running"},
        ]
    },
}
PAGE_2 = {
    "_links": {
        "self": {"href": f"{BASE_URL}/activityList?startDate=x"}
    },  # sin "next": última página
    "count": 1,
    "_embedded": {
        "activityList": [
            {
                "id": "act-20",
                "date": "2026-09-20T06:00:00.000Z",
                "sportType": "strength_training",
            },
        ]
    },
}


def make_http():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = PAGE_2 if "startDate" in request.url.params else PAGE_1
        return httpx.Response(200, json=payload)

    http = HttpClient(httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    return http, seen


def test_pagina_siguiendo_next_href_y_autentica_con_bearer(conn):
    http, seen = make_http()
    res = sync_activities(conn, http, "token-falso", days=30, today=date(2026, 9, 27))
    assert (res.fetched, res.inserted) == (3, 3)
    assert len(seen) == 2  # página 1 + página 2 (la 2ª no tiene "next": para ahí)

    first = seen[0]
    assert first.url.path == "/api/oauth/v2/activityList"
    assert "startDate" not in first.url.params  # primera página: sin fecha, las más recientes
    assert first.headers["Authorization"] == "Bearer token-falso"

    second = seen[1]
    assert second.url == httpx.URL(PAGE_1["_links"]["next"]["href"])  # sigue el href tal cual

    rows = conn.execute("SELECT day, body FROM raw_tredict_activity ORDER BY day").fetchall()
    assert [r[0] for r in rows] == [date(2026, 9, 20), date(2026, 9, 26), date(2026, 9, 27)]
    assert json.loads(rows[0][1])["sportType"] == "strength_training"

    status = conn.execute(
        "SELECT device_id, last_ok IS NOT NULL FROM source_status "
        "WHERE source='tredict' AND endpoint='activity'"
    ).fetchone()
    assert status == ("global", True)


def test_se_detiene_al_llegar_a_actividades_anteriores_a_la_ventana(conn):
    """Con days=5 (ventana 23-27 sep), act-20 (20 sep) queda fuera: se descubre en la
    página 2 y ahí se detiene, sin pedir una página 3."""
    http, seen = make_http()
    res = sync_activities(conn, http, "token-falso", days=5, today=date(2026, 9, 27))
    assert (res.fetched, res.inserted) == (2, 2)  # solo act-27 y act-26; act-20 descartada
    assert len(seen) == 2  # necesita la página 2 para descubrir el límite
    rows = conn.execute("SELECT count(*) FROM raw_tredict_activity").fetchone()
    assert rows[0] == 2


def test_sincronizar_dos_veces_no_duplica(conn):
    http1, _ = make_http()
    sync_activities(conn, http1, "token-falso", days=30, today=date(2026, 9, 27))
    http2, _ = make_http()
    res = sync_activities(conn, http2, "token-falso", days=30, today=date(2026, 9, 27))
    assert (res.fetched, res.inserted, res.unchanged) == (3, 0, 3)
    assert (
        conn.execute("SELECT count(*) FROM raw_payload WHERE source='tredict'").fetchone()[0] == 3
    )
