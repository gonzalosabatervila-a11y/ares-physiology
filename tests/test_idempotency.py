"""Capa bruta solo-añadir: repetir no duplica; un cambio real añade una versión nueva."""

from __future__ import annotations

import copy
from datetime import date

from test_intervals_contract import FIXTURE, make_http

from ares.connectors.intervals import sync_wellness


def test_sincronizar_dos_veces_no_duplica(conn):
    sync_wellness(conn, make_http(FIXTURE, []), "k", "0", 3, today=date(2026, 9, 27))
    res = sync_wellness(conn, make_http(FIXTURE, []), "k", "0", 3, today=date(2026, 9, 27))
    assert (res.fetched, res.inserted, res.unchanged) == (3, 0, 3)
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == 3


def test_dato_corregido_se_anade_sin_borrar_el_anterior(conn):
    sync_wellness(conn, make_http(FIXTURE, []), "k", "0", 3, today=date(2026, 9, 27))
    changed = copy.deepcopy(FIXTURE)
    changed[2]["restingHR"] = 45  # intervals.icu recalcula el día
    res = sync_wellness(conn, make_http(changed, []), "k", "0", 3, today=date(2026, 9, 27))
    assert res.inserted == 1
    n = conn.execute("SELECT count(*) FROM raw_payload WHERE day = DATE '2026-09-27'").fetchone()
    assert n[0] == 2
