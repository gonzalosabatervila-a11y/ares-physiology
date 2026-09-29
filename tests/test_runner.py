"""Decisión incremental/backfill y contabilidad en job_runs, compartida por
`ares sync` y el planificador de `ares serve`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import structlog
from test_intervals_contract import FIXTURE, make_http

from ares import runner


def _logger():
    return structlog.get_logger("test")


def test_sin_last_ok_pide_backfill_completo(conn):
    days, backfill = runner.days_to_request(
        conn, "intervals", "wellness", incremental=3, backfill_max=30
    )
    assert (days, backfill) == (30, True)


def test_con_last_ok_reciente_es_incremental(conn):
    conn.execute(
        "INSERT INTO source_status (source, endpoint, last_ok) VALUES "
        "('intervals','wellness', now())"
    )
    days, backfill = runner.days_to_request(
        conn, "intervals", "wellness", incremental=3, backfill_max=30
    )
    assert (days, backfill) == (3, False)


def test_con_last_ok_antiguo_vuelve_a_backfill(conn):
    old = datetime.now(UTC) - timedelta(days=10)
    conn.execute(
        "INSERT INTO source_status (source, endpoint, last_ok) VALUES ('intervals','wellness', ?)",
        [old],
    )
    days, backfill = runner.days_to_request(
        conn, "intervals", "wellness", incremental=3, backfill_max=30
    )
    assert (days, backfill) == (30, True)


def test_run_source_sync_sin_clave_lanza_skipped(conn, settings):
    with pytest.raises(runner.SyncSkipped):
        runner.run_source_sync(
            conn, "intervals", settings, logger=_logger(), secret_getter=lambda _n: None
        )


def test_run_source_sync_ok_registra_job_run_y_result(conn, settings):
    http = make_http(FIXTURE, [])
    res = runner.run_source_sync(
        conn,
        "intervals",
        settings,
        logger=_logger(),
        secret_getter=lambda _n: "clave-falsa",
        http=http,
        days=3,
    )
    assert (res.fetched, res.inserted, res.backfill) == (3, 3, False)
    row = conn.execute("SELECT job, status FROM job_runs ORDER BY started DESC LIMIT 1").fetchone()
    assert row == ("sync_intervals", "ok")


def test_run_all_una_fuente_fallida_no_bloquea_la_otra(conn, settings, monkeypatch):
    """Tredict falla; intervals.icu debe sincronizar igualmente (§8: "una fuente
    fallida no bloquea las demás") y quedar registrado en job_runs."""
    from ares import runner as runner_mod
    from ares.connectors.intervals import sync_wellness as real_sync_wellness

    monkeypatch.setattr(runner_mod, "get_secret", lambda _name: "clave-falsa")

    def ok_intervals(conn_, _http_ignored, key_, athlete_, days_):
        return real_sync_wellness(conn_, make_http(FIXTURE, []), key_, athlete_, days_)

    def boom_tredict(*_a, **_k):
        raise RuntimeError("Tredict caído")

    monkeypatch.setattr(runner_mod, "sync_wellness", ok_intervals)
    monkeypatch.setattr(runner_mod, "sync_activities", boom_tredict)

    results = runner.run_all(conn, settings, _logger())

    # El fallo de Tredict ya queda registrado (error logueado + job_runs, ver abajo);
    # run_all no está obligado a devolverlo, solo a no romperse por él.
    ok = [r for r in results if isinstance(r, runner.RunResult)]
    assert [r.source for r in ok] == ["intervals"]
    assert ok[0].fetched == 3

    rows = conn.execute("SELECT job, status FROM job_runs ORDER BY job").fetchall()
    assert set(rows) == {("sync_intervals", "ok"), ("sync_tredict", "error")}
