"""`ares serve`: el único proceso propietario de DuckDB (Implementation Plan v0.2
FINAL, §1 y §7). Abre la conexión una vez, aplica migraciones, arranca el
planificador interno y se queda vivo hasta recibir una señal de apagado.

v0.3: proceso + planificador + logs. La API local de administración y la PWA
(servidas por el mismo proceso) llegan cuando se construya `app/` — no antes,
para no levantar FastAPI sin nada real que servir todavía.
"""

from __future__ import annotations

import signal
import time
from types import FrameType

from . import db, log
from .config import load_settings
from .scheduler import AresScheduler


def _install_signal_handlers(stop: list[bool]) -> None:
    def handler(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        stop[0] = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def run(run_once: bool = False) -> int:
    settings = load_settings()
    logger = log.setup(settings.log_dir)
    logger.info("serve_starting", data_dir=str(settings.data_dir))

    conn = db.connect(settings.db_path)
    try:
        applied = db.migrate(conn, settings.migrations_dir)
        if applied:
            logger.info("migrations_applied", versions=applied)

        scheduler = AresScheduler(conn, settings, logger)
        scheduler.run_now()  # primera pasada al arrancar, sin esperar al próximo tramo
        if run_once:
            return 0

        scheduler.start()
        stop = [False]
        _install_signal_handlers(stop)
        logger.info(
            "serve_ready",
            next_runs={
                k: (v.isoformat() if v else None) for k, v in scheduler.next_run_times.items()
            },
        )
        try:
            while not stop[0]:
                time.sleep(1.0)
        finally:
            scheduler.shutdown()
    finally:
        conn.close()
        logger.info("serve_stopped")
    return 0
