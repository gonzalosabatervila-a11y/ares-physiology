"""Logs estructurados en JSON: consola y fichero ares.jsonl. Nunca tokens."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog

_configured = False


def setup(log_dir: Path) -> structlog.stdlib.BoundLogger:
    global _configured
    if not _configured:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler_file = logging.FileHandler(log_dir / "ares.jsonl", encoding="utf-8")
        handler_err = logging.StreamHandler(sys.stderr)
        handler_err.setLevel(logging.WARNING)
        logging.basicConfig(
            level=logging.INFO, format="%(message)s", handlers=[handler_file, handler_err]
        )
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _configured = True
    return structlog.get_logger("ares")
