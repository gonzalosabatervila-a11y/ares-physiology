"""Planificador interno de `ares serve`: cola serializada de tareas dentro del
mismo proceso que posee la conexión a DuckDB (Implementation Plan v0.2 FINAL, §7).
Nada fuera de este proceso escribe en la base mientras el servicio corre.
"""

from __future__ import annotations

import threading
from datetime import datetime
from datetime import time as dtime

import duckdb
import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import runner
from .config import Settings

# ARES mantiene los datos frescos durante el día. La sincronización se ejecuta
# cada 10 minutos entre las 06:00 y las 23:50 (Europe/Madrid por defecto).
# El bloqueo interno evita que dos pasadas se solapen.
SYNC_TRIGGER = CronTrigger(hour="6-23", minute="*/10")


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
        self._lock = threading.Lock()

    def _tick(self, job: str) -> None:
        # Una sola sincronización a la vez: el refresh token de Polar rota en cada renovación y
        # dos renovaciones simultáneas lo romperían. Si aún hay una en marcha, esta se omite.
        if not self._lock.acquire(blocking=False):
            self.logger.warning("scheduler_skip_overlap", job=job)
            return
        try:
            self.logger.info("scheduler_tick", job=job)
            cur = self.conn.cursor()  # cada hilo, su propio cursor (la conexión no es segura)
            try:
                runner.run_all(cur, self.settings, self.logger)
            finally:
                cur.close()
        finally:
            self._lock.release()

    def start(self) -> None:
        self._scheduler.add_job(
            self._tick,
            SYNC_TRIGGER,
            kwargs={"job": "sync10"},
            id="sync10",
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
