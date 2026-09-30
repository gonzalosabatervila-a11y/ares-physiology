from __future__ import annotations

from pathlib import Path

import pytest

from ares import db
from ares.config import REPO_ROOT, Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "ares-data",
        tz="Europe/Madrid",
        rules_version="1.2",
        filter_version="0.3",
        device_id="polar-loop-1",
        intervals_athlete_id="0",
        backfill_max_days=30,
        migrations_dir=REPO_ROOT / "migrations",
        polar_redirect_uri="http://localhost:8765/callback",
    )


@pytest.fixture
def conn(settings: Settings):
    c = db.connect(settings.db_path)
    db.migrate(c, settings.migrations_dir)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _aislar_llavero(monkeypatch):
    """Ninguna prueba lee ni escribe el llavero real: en tu Mac guarda tokens de Polar que se
    renuevan al usarse, y una prueba que llegara a ellos podría gastarlos o llamar a la red."""
    almacen: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("ares.config.keyring.get_password", lambda s, n: almacen.get((s, n)))
    monkeypatch.setattr(
        "ares.config.keyring.set_password", lambda s, n, v: almacen.__setitem__((s, n), v)
    )
