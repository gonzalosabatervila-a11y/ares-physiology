"""WHOOP en el runner: la carga histórica solo se lanza con secretos y token válido (si no, se
registra y se sigue); después, modo incremental; de día solo se pide el ciclo; tras cada
sincronización, las noches se recalculan desde lo bruto."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from whoop_synthetic import api, authorize_store, merge, night

from ares import runner
from ares.config import set_secret


class Recorder:
    """Logger mínimo que guarda los eventos para comprobarlos."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def _log(self, level: str, event: str, **kw: object) -> None:
        self.events.append((level, event, kw))

    def info(self, event: str, **kw: object) -> None:
        self._log("info", event, **kw)

    def warning(self, event: str, **kw: object) -> None:
        self._log("warning", event, **kw)

    def error(self, event: str, **kw: object) -> None:
        self._log("error", event, **kw)

    def names(self) -> list[str]:
        return [e for _, e, _ in self.events]


def data_recent(days: int = 10) -> dict:
    today = datetime.now(UTC).date()
    return merge(
        *[night(i + 1, (today - timedelta(days=days - i)).isoformat()) for i in range(days)]
    )


def starts(seen: list[httpx.Request], path: str) -> list[datetime]:
    out = []
    for r in seen:
        u = urlparse(str(r.url))
        if u.path == path and "nextToken" not in parse_qs(u.query):
            out.append(datetime.fromisoformat(parse_qs(u.query)["start"][0].replace("Z", "+00:00")))
    return out


def test_sin_secretos_no_hay_carga_historica_se_registra_y_se_sigue(conn, settings):
    log = Recorder()
    out = runner.run_all(conn, settings, log)  # type: ignore[arg-type]
    skipped = [r for r in out if isinstance(r, runner.SyncSkipped)]
    assert any("whoop-auth" in str(r) for r in skipped)
    assert "whoop_history_pending" in log.names()
    assert conn.execute("SELECT count(*) FROM raw_payload WHERE source='whoop'").fetchone()[0] == 0


def test_con_token_caducado_y_refresh_gastado_tampoco(conn, settings):
    authorize_store(set_secret, expiry=datetime.now(UTC) - timedelta(minutes=1))
    token_http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    )
    log = Recorder()
    try:
        runner.run_source_sync(conn, "whoop", settings, logger=log, token_http=token_http)  # type: ignore[arg-type]
    except runner.SyncSkipped as exc:
        assert "invalid_grant" in str(exc)
    else:
        raise AssertionError("debía omitirse")
    assert "whoop_history_pending" in log.names()


def test_primera_vez_con_token_valido_hace_la_carga_historica_y_las_noches(conn, settings):
    authorize_store(set_secret)
    seen: list[httpx.Request] = []
    res = runner.run_source_sync(
        conn,
        "whoop",
        settings,
        logger=Recorder(),
        http=api(data_recent(), seen=seen),  # type: ignore[arg-type]
    )
    assert res.history and res.backfill and res.days_used == settings.whoop_history_days
    assert res.nights == 10 and res.fetched == 30
    (start,) = starts(seen, "/developer/v2/recovery")
    assert datetime.now(UTC) - start > timedelta(days=settings.whoop_history_days - 1)
    run = conn.execute(
        "SELECT job, status, detail FROM job_runs ORDER BY started DESC LIMIT 1"
    ).fetchone()
    assert run[:2] == ("sync_whoop", "ok")
    detail = json.loads(run[2])
    assert detail["history"] is True and detail["nights"] == 10
    assert conn.execute("SELECT count(*) FROM daily_metrics").fetchone()[0] == 10


def test_despues_es_incremental_y_recalcula_solo_la_ventana(conn, settings):
    authorize_store(set_secret)
    data = data_recent()
    runner.run_source_sync(conn, "whoop", settings, logger=Recorder(), http=api(data))  # type: ignore[arg-type]
    seen: list[httpx.Request] = []
    res = runner.run_source_sync(
        conn,
        "whoop",
        settings,
        logger=Recorder(),
        http=api(data, seen=seen),  # type: ignore[arg-type]
    )
    assert not res.history and not res.backfill and res.days_used == runner.INCREMENTAL_DAYS
    assert res.inserted == 0
    assert res.nights is not None and res.nights <= runner.INCREMENTAL_DAYS + 1
    assert conn.execute("SELECT count(*) FROM daily_metrics").fetchone()[0] == 10


def test_de_dia_solo_se_pide_el_ciclo(conn, settings, monkeypatch):
    authorize_store(set_secret)
    data = data_recent()
    runner.run_source_sync(conn, "whoop", settings, logger=Recorder(), http=api(data))  # type: ignore[arg-type]
    seen: list[httpx.Request] = []
    monkeypatch.setattr("ares.runner.HttpClient", lambda: api(data, seen=seen))
    runner.run_all(conn, settings, Recorder(), job="day")  # type: ignore[arg-type]
    whoop_paths = {urlparse(str(r.url)).path for r in seen if "whoop" in str(r.url)}
    assert whoop_paths == {"/developer/v2/cycle", "/developer/v2/activity/workout"}


def test_por_la_manana_se_piden_las_cuatro_colecciones(conn, settings, monkeypatch):
    authorize_store(set_secret)
    seen: list[httpx.Request] = []
    monkeypatch.setattr("ares.runner.HttpClient", lambda: api(data_recent(), seen=seen))
    runner.run_all(conn, settings, Recorder(), job="morning")  # type: ignore[arg-type]
    whoop_paths = {urlparse(str(r.url)).path for r in seen if "whoop" in str(r.url)}
    assert whoop_paths == {
        "/developer/v2/recovery",
        "/developer/v2/activity/sleep",
        "/developer/v2/cycle",
        "/developer/v2/activity/workout",
    }
