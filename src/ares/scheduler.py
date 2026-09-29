"""Planificador interno de `ares serve`: cola serializada de tareas dentro del
mismo proceso que posee la conexión a DuckDB (Implementation Plan v0.2 FINAL, §7).
Nada fuera de este proceso escribe en la base mientras el servicio corre.
"""

from __future__ import annotations

from datetime import datetime
from datetime import time as dtime

import duckdb
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import runner
from .config import Settings

# Horarios de Implementation Plan v0.2 FINAL §7. Copia y backup quedan fuera del
# alcance de v0.3 (necesitan CHECKPOINT/EXPORT DATABASE, aún no escritos).
MORNING_TRIGGER = CronTrigger(hour="6-10", minute="0,30")
DAY_TRIGGER = CronTrigger(hour="11-23", minute=0)


class AresScheduler:
    """Envuelve APScheduler para que todas las tareas pasen por `run_all`,
    con el mismo `conn` que el resto del proceso, nunca una conexión nueva."""

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.logger = logger
        self._scheduler = BackgroundScheduler(timezone=settings.tz)

    def _tick(self, job: str) -> None:
        self.logger.info("scheduler_tick", job=job)
        runner.run_all(self.conn, self.settings, self.logger)

    def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            MORNING_TRIGGER,
            kwargs={"job": "morning"},
            id="morning",
            replace_existing=True,
            misfire_grace_time=600,
        )
        self._scheduler.add_job(
            self._tick,
            DAY_TRIGGER,
            kwargs={"job": "day"},
            id="day",
            replace_existing=True,
            misfire_grace_time=600,
        )
        self._scheduler.start()
        self.logger.info("scheduler_started", jobs=[j.id for j in self._scheduler.get_jobs()])

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)
        self.logger.info("scheduler_stopped")

    def run_now(self) -> None:
        """Ejecuta una sincronización inmediata, fuera del horario (p. ej. al arrancar)."""
        self._tick("manual")

    @property
    def next_run_times(self) -> dict[str, datetime | None]:
        return {j.id: j.next_run_time for j in self._scheduler.get_jobs()}


def in_morning_window(now: dtime) -> bool:
    return dtime(6, 0) <= now <= dtime(10, 30)
