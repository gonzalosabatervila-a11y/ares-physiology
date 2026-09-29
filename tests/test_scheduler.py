"""El planificador registra los dos tramos horarios del plan (mañana y día)
y `run_now` ejecuta una pasada inmediata sin esperar al cron."""

from __future__ import annotations

import structlog

from ares.scheduler import AresScheduler, in_morning_window


def test_registra_las_dos_tareas_con_sus_horarios(conn, settings):
    sch = AresScheduler(conn, settings, structlog.get_logger("test"))
    sch.start()
    try:
        ids = set(sch.next_run_times.keys())
        assert ids == {"morning", "day"}
    finally:
        sch.shutdown(wait=False)


def test_run_now_ejecuta_sin_arrancar_el_planificador(conn, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ares.scheduler.runner.run_all",
        lambda conn_, settings_, logger_: calls.append(1),
    )
    sch = AresScheduler(conn, settings, structlog.get_logger("test"))
    sch.run_now()
    assert calls == [1]


def test_in_morning_window():
    from datetime import time

    assert in_morning_window(time(6, 0)) is True
    assert in_morning_window(time(10, 30)) is True
    assert in_morning_window(time(10, 31)) is False
    assert in_morning_window(time(5, 59)) is False
