"""Registro de ejecuciones en job_runs, con versión del software y host."""

from __future__ import annotations

import json
import platform
import subprocess
import uuid
from datetime import UTC, datetime

import duckdb

from . import __version__
from .config import REPO_ROOT


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "sin-commit"
    except Exception:
        return "sin-git"


def start(conn: duckdb.DuckDBPyConnection, job: str, rules_version: str) -> str:
    run_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO job_runs (run_id, job, started, status, git_commit, app_version, host, "
        "rules_version) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)",
        [run_id, job, datetime.now(UTC), git_commit(), __version__, platform.node(), rules_version],
    )
    return run_id


def finish(conn: duckdb.DuckDBPyConnection, run_id: str, status: str, detail: dict) -> None:
    conn.execute(
        "UPDATE job_runs SET ended = ?, status = ?, detail = ? WHERE run_id = ?",
        [datetime.now(UTC), status, json.dumps(detail, ensure_ascii=False), run_id],
    )
