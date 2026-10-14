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


def test_intervalos_503_activa_enfriamiento_temporal_sin_cambiar_brutos(conn):
    from ares.connectors.base import mark_status

    original = conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0]
    mark_status(
        conn, source="intervals", endpoint="wellness", ok=False,
        error="HTTP 503 en https://intervals.icu/api/v1/athlete/0/wellness",
    )
    row = conn.execute(
        "SELECT last_error FROM source_status WHERE source='intervals'"
    ).fetchone()
    assert row and row[0] is not None
    failure = row[0]
    remaining = runner.intervals_503_cooldown(
        conn, now=failure + timedelta(minutes=2)
    )
    assert remaining == timedelta(minutes=28)
    assert runner.intervals_503_cooldown(
        conn, now=failure + timedelta(minutes=31)
    ) is None
    assert conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0] == original


def test_cuando_intervalos_devuelve_503_se_siguen_las_otras_fuentes(conn, settings, monkeypatch):
    from ares.connectors.base import mark_status

    mark_status(
        conn, source="intervals", endpoint="wellness", ok=False,
        error="HTTP 503 en https://intervals.icu/api/v1/athlete/0/wellness",
    )
    attempted = []
    events = []

    def fake_sync(conn_, source, settings_, **kwargs):
        attempted.append(source)
        return runner.RunResult(source, 0, 0, 3, False)

    class Logger:
        def warning(self, name, **fields):
            events.append((name, fields))

    monkeypatch.setattr(runner, "run_source_sync", fake_sync)
    result = runner.run_all(conn, settings, Logger())
    assert attempted == ["tredict", "whoop"]
    assert isinstance(result[0], runner.SyncSkipped)
    assert [r.source for r in result[1:]] == ["tredict", "whoop"]
    assert events[0][0] == "sync_deferred"
    assert events[0][1]["reason"] == "HTTP 503 temporal"
    assert conn.execute("SELECT count(*) FROM job_runs").fetchone()[0] == 0


def test_solo_503_reciente_y_no_resuelto_bloquea_reintento(conn):
    from ares.connectors.base import mark_status

    # Los fallos de autenticación no causan apagados artificiales.
    mark_status(conn, source="intervals", endpoint="wellness", ok=False,
                error="HTTP 401 en https://intervals.icu/api/v1/athlete/0/wellness")
    assert runner.intervals_503_cooldown(conn) is None

    mark_status(conn, source="intervals", endpoint="wellness", ok=False,
                error="HTTP 503 en https://intervals.icu/api/v1/athlete/0/wellness")
    assert runner.intervals_503_cooldown(conn) is not None
    mark_status(conn, source="intervals", endpoint="wellness", ok=True)
    assert runner.intervals_503_cooldown(conn) is None
