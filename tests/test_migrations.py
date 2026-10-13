"""schema_version: qué migraciones se han aplicado, con hash verificado desde el primer día."""

from __future__ import annotations

import hashlib
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from ares import db
from ares.config import REPO_ROOT

EXPECTED = {1: "raw", 2: "core", 3: "decisions", 4: "provider_whoop"}


def test_schema_version_registra_las_migraciones_con_hash(conn, settings):
    rows = conn.execute(
        "SELECT version, name, sha256 FROM schema_version ORDER BY version"
    ).fetchall()
    assert [(v, n) for v, n, _ in rows] == sorted(EXPECTED.items())
    for v, _, sha in rows:
        path = next(settings.migrations_dir.glob(f"{v:03d}_*.sql"))
        assert sha == hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert db.current_version(conn) == 4


def test_migrar_dos_veces_no_hace_nada(conn, settings):
    assert db.migrate(conn, settings.migrations_dir) == []
    assert conn.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 4


def test_migracion_editada_tras_aplicarse_se_detecta(settings, tmp_path: Path):
    mig = tmp_path / "migrations"
    shutil.copytree(settings.migrations_dir, mig)
    c = db.connect(tmp_path / "t.duckdb")
    db.migrate(c, mig)
    (mig / "002_core.sql").write_text((mig / "002_core.sql").read_text() + "\n-- cambio\n")
    with pytest.raises(db.MigrationError, match="ha cambiado"):
        db.migrate(c, mig)
    c.close()


def test_tablas_clave_existen(conn):
    tables = {
        r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    for t in [
        "raw_payload",
        "raw_polar_ppi",
        "raw_h10_rr",
        "raw_checkin_events",
        "daily_metrics",
        "source_status",
        "job_runs",
        "decisions",
        "decision_conflicts",
        "decisions_recomputed",
        "gate_results",
        "checkin_latest",
    ]:
        assert t in tables


def test_source_status_device_id_por_defecto_global_y_nunca_null(conn):
    conn.execute("INSERT INTO source_status (source, endpoint) VALUES ('intervals', 'wellness')")
    assert conn.execute("SELECT device_id FROM source_status").fetchone()[0] == "global"
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("INSERT INTO source_status VALUES ('polar','ppi',NULL,NULL,NULL,NULL)")


def test_decisions_recomputed_admite_varias_simulaciones_mismo_dia_y_reglas(conn):
    for rid, fv in [("r1", "0.3"), ("r2", "0.4")]:
        conn.execute(
            "INSERT INTO decisions_recomputed (recompute_id, d, rules_version, filter_version, "
            "computed_at) VALUES (?, DATE '2026-10-20', '1.2', ?, now())",
            [rid, fv],
        )
    assert conn.execute("SELECT count(*) FROM decisions_recomputed").fetchone()[0] == 2


def _to_crlf(mig_dir: Path) -> None:
    for f in mig_dir.glob("*.sql"):
        f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


def test_los_saltos_de_linea_no_cuentan_como_edicion(settings, tmp_path: Path):
    mig = tmp_path / "migrations"
    shutil.copytree(settings.migrations_dir, mig)
    c = db.connect(tmp_path / "t.duckdb")
    db.migrate(c, mig)
    _to_crlf(mig)  # el mismo SQL, con otros saltos de línea
    assert db.migrate(c, mig) == []
    c.close()


def test_base_creada_en_windows_con_huella_crlf_sigue_valida_con_ficheros_lf(
    settings, tmp_path: Path
):
    """Caso real del HP (30/09/2026): el clon con Git dejó CRLF y la base guardó esa huella;
    después llegó el mismo código por zip, con LF."""
    mig = tmp_path / "migrations"
    shutil.copytree(settings.migrations_dir, mig)
    c = db.connect(tmp_path / "t.duckdb")
    db.migrate(c, mig)
    for m in db.discover(mig):
        crlf = m.path.read_bytes().replace(b"\n", b"\r\n")
        c.execute(
            "UPDATE schema_version SET sha256 = ? WHERE version = ?",
            [hashlib.sha256(crlf).hexdigest(), m.version],
        )
    assert db.migrate(c, mig) == []
    c.close()


def test_un_cambio_real_se_sigue_detectando_aunque_haya_crlf(settings, tmp_path: Path):
    mig = tmp_path / "migrations"
    shutil.copytree(settings.migrations_dir, mig)
    c = db.connect(tmp_path / "t.duckdb")
    db.migrate(c, mig)
    _to_crlf(mig)
    with (mig / "001_raw.sql").open("ab") as f:
        f.write(b"-- cambio real\r\n")
    with pytest.raises(db.MigrationError, match="ha cambiado"):
        db.migrate(c, mig)
    c.close()


def test_una_base_nueva_guarda_la_huella_canonica_sea_cual_sea_el_salto_de_linea(
    settings, tmp_path: Path
):
    mig = tmp_path / "migrations"
    shutil.copytree(settings.migrations_dir, mig)
    _to_crlf(mig)
    c = db.connect(tmp_path / "t.duckdb")
    db.migrate(c, mig)
    for v, sha in c.execute("SELECT version, sha256 FROM schema_version").fetchall():
        lf = next(mig.glob(f"{v:03d}_*.sql")).read_bytes().replace(b"\r\n", b"\n")
        assert sha == hashlib.sha256(lf).hexdigest()
    c.close()


# ------------------------------------------------------------------ migración 004 (WHOOP)
# Base sintética creada con 001–003 y datos en todas las capas, incluidos los del proveedor
# anterior: la capa bruta queda idéntica (recuentos y hashes), las decisiones no se pierden y
# el esquema es el esperado.

# Lo que la 004 no puede cambiar ni en una fila
PRESERVED = (
    "decisions",
    "decision_conflicts",
    "decisions_recomputed",
    "baselines",
    "gate_results",
    "ppi_quality",
    "source_status",
    "job_runs",
)

DAILY_METRICS_V03 = [
    "local_sleep_date",
    "device_id",
    "sleep_start",
    "sleep_end",
    "source_tz",
    "sleep_min",
    "rmssd_ms",
    "ln_rmssd",
    "hrv_tag",
    "hrv_origin",
    "rhr",
    "resp_rate",
    "spo2",
    "skin_temp",
    "provider_recovery",
    "steps_whoop_cycle",
    "score_state",
    "calibrating",
    "ctl",
    "atl",
    "quality",
    "algo_version",
    "adapter_version",
    "whoop_sleep_id",
    "whoop_cycle_id",
    "night_check",
]


def seed_legacy(conn: duckdb.DuckDBPyConnection) -> None:
    """Una base v0.2 con datos en todas las tablas, también los del proveedor anterior."""
    legacy = "polar"  # el proveedor anterior, tal como está en 001
    rows = [
        (
            legacy,
            "nightly-recharge-results",
            "2026-09-28",
            "loop-1",
            "a1",
            '{"nightlyRechargeResults": [{"meanNightlyRecoveryRmssd": 41}]}',
        ),
        (legacy, "sleeps", "2026-09-28", "loop-1", "a2", '{"nights": [{"duration": "26400s"}]}'),
        (legacy, "continuous-samples", "2026-09-28", "loop-1", "a3", '{"samples": [61, 60]}'),
        (legacy, "activity", "2026-09-28", "loop-1", "a4", '{"steps": 9120}'),
        ("intervals", "wellness", "2026-09-28", None, "b1", '{"id": "2026-09-28", "ctl": 57.1}'),
        ("intervals", "wellness", "2026-09-29", None, "b2", '{"id": "2026-09-29", "ctl": 57.4}'),
        ("tredict", "activity", "2026-09-28", None, "c1", '{"id": 1, "distance": 10020}'),
        ("tredict", "metrics", "2026-09-28", None, "c2", '{"vo2max": 54}'),
    ]
    for source, endpoint, day, dev, sha, body in rows:
        conn.execute(
            "INSERT INTO raw_payload VALUES "
            "(?, ?, ?, ?, TIMESTAMPTZ '2026-09-29 06:00:00+00', ?, ?)",
            [source, endpoint, day, dev, sha, body],
        )
    for i in range(50):
        conn.execute(
            f"INSERT INTO raw_{legacy}_ppi VALUES ('loop-1', DATE '2026-09-28', ?, ?, 5, true, "
            "false, false, 'a1')",
            [i * 1000, 950 + i],
        )
    conn.execute(
        "INSERT INTO raw_h10_rr VALUES ('h10-1', TIMESTAMPTZ '2026-09-27 23:00:00+00', 1010, 'f1'),"
        " ('h10-1', TIMESTAMPTZ '2026-09-27 23:00:01+00', 1002, 'f1')"
    )
    conn.execute(
        "INSERT INTO raw_checkin_events VALUES ('ev1', TIMESTAMPTZ '2026-09-28 06:30:00+00', "
        "DATE '2026-09-28', '{\"legs\": 6, \"fatigue\": 4}')"
    )
    conn.execute(
        "INSERT INTO devices VALUES ('loop-1', 'Loop', DATE '2026-09-20', DATE '2026-09-29')"
    )
    conn.execute(
        "INSERT INTO baselines VALUES ('b-1', 'loop-1', DATE '2026-09-20', 0, 'provisional', "
        "'0.3', '{}')"
    )
    conn.execute(
        "INSERT INTO ppi_quality VALUES ('loop-1', DATE '2026-09-28', '0.3', 100, 3, 2, 1, 0, 0, "
        "6.5, 0.9)"
    )
    conn.execute(
        "INSERT INTO daily_metrics (local_sleep_date, device_id, sleep_min, battery_ran_out, "
        "rmssd_ms, quality, filter_version) VALUES (DATE '2026-09-28', 'loop-1', 410, false, "
        "41.0, 'excluded', '0.3')"
    )
    conn.execute(
        "INSERT INTO decisions VALUES (DATE '2026-09-28', 'bloqueada', NULL, '[]', '{}', true, "
        "'h-1', '{}', NULL, 'v0', '0.3', '1.2', TIMESTAMPTZ '2026-09-28 07:00:00+00')"
    )
    conn.execute(
        "INSERT INTO decision_conflicts VALUES (DATE '2026-09-28', "
        "TIMESTAMPTZ '2026-09-28 08:00:00+00', 'h-1', 'h-2', '{}')"
    )
    conn.execute(
        "INSERT INTO decisions_recomputed (recompute_id, d, rules_version, computed_at) "
        "VALUES ('r1', DATE '2026-09-28', '1.2', TIMESTAMPTZ '2026-09-29 07:00:00+00')"
    )
    conn.execute(
        "INSERT INTO gate_results VALUES (TIMESTAMPTZ '2026-09-29 07:00:00+00', 'none', '0.3', 0, "
        "'{}', '{}')"
    )
    conn.execute(
        "INSERT INTO source_status VALUES ('intervals', 'wellness', 'global', "
        "TIMESTAMPTZ '2026-09-29 06:00:00+00', NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO job_runs VALUES ('run-1', 'sync_intervals', "
        "TIMESTAMPTZ '2026-09-29 06:00:00+00', TIMESTAMPTZ '2026-09-29 06:00:05+00', "
        "'ok', 'abc123', '0.1.0', 'hp', '1.2', '{}')"
    )


@pytest.fixture
def legacy_db(tmp_path: Path):
    """Base creada solo con 001–003 y sembrada, como la de producción antes de la 004."""
    old = tmp_path / "migrations-v02"
    old.mkdir()
    for name in ("001_raw.sql", "002_core.sql", "003_decisions.sql"):
        shutil.copy(REPO_ROOT / "migrations" / name, old / name)
    conn = db.connect(tmp_path / "copia.duckdb")
    assert db.migrate(conn, old) == [1, 2, 3]
    seed_legacy(conn)
    yield conn
    conn.close()


def snapshot(conn: duckdb.DuckDBPyConnection) -> dict[str, tuple[int, str]]:
    return db.fingerprint(conn, db.raw_objects(conn) + list(PRESERVED))


def test_la_004_deja_la_capa_bruta_y_las_decisiones_identicas(legacy_db):
    before = snapshot(legacy_db)
    assert before["raw_payload"][0] == 8 and before["decisions"][0] == 1
    assert db.migrate(legacy_db, REPO_ROOT / "migrations") == [4]
    after = db.fingerprint(legacy_db, list(before))
    assert after == before


def test_la_004_crea_las_vistas_de_whoop_y_conserva_las_del_proveedor_anterior(legacy_db):
    before = set(db.raw_objects(legacy_db))
    db.migrate(legacy_db, REPO_ROOT / "migrations")
    after = set(db.raw_objects(legacy_db))
    assert before <= after
    assert after - before == {
        "raw_whoop_recovery",
        "raw_whoop_sleep",
        "raw_whoop_cycle",
        "raw_whoop_workout",
    }
    assert {"raw_polar_ppi", "raw_polar_nightly", "raw_polar_sleep", "raw_polar_hr"} <= after


def test_la_004_recrea_daily_metrics_con_la_forma_v03(legacy_db):
    db.migrate(legacy_db, REPO_ROOT / "migrations")
    cols = [
        r[0]
        for r in legacy_db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'daily_metrics' ORDER BY ordinal_position"
        ).fetchall()
    ]
    assert cols == DAILY_METRICS_V03
    assert legacy_db.execute("SELECT count(*) FROM daily_metrics").fetchone()[0] == 0
    with pytest.raises(duckdb.ConstraintException):  # clave (fecha, dispositivo)
        legacy_db.execute(
            "INSERT INTO daily_metrics (local_sleep_date, device_id) VALUES "
            "(DATE '2026-10-01', 'x'), (DATE '2026-10-01', 'x')"
        )


def test_la_004_anade_provider_a_devices_sin_tocar_las_filas(legacy_db):
    db.migrate(legacy_db, REPO_ROOT / "migrations")
    assert legacy_db.execute("SELECT * FROM devices").fetchall() == [
        ("loop-1", "Loop", date(2026, 9, 20), date(2026, 9, 29), None)
    ]


def test_la_004_no_contiene_drop_de_lo_bruto_ni_delete_ni_update():
    sql = (REPO_ROOT / "migrations" / "004_provider_whoop.sql").read_text().upper()
    code = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    assert code.count("DROP ") == 1 and "DROP TABLE DAILY_METRICS;" in code
    for word in ("DELETE ", "UPDATE ", "TRUNCATE ", "DROP VIEW", "RAW_PAYLOAD SET"):
        assert word not in code
    assert "POLAR" not in sql  # sin el nombre del proveedor anterior


def test_un_fallo_a_mitad_de_la_004_no_deja_nada_a_medias(legacy_db, tmp_path):
    mig = tmp_path / "migrations-rota"
    shutil.copytree(REPO_ROOT / "migrations", mig)
    (mig / "004_provider_whoop.sql").write_text(
        (mig / "004_provider_whoop.sql").read_text() + "\nSELECT * FROM tabla_que_no_existe;\n"
    )
    before = snapshot(legacy_db)
    with pytest.raises(duckdb.CatalogException):
        db.migrate(legacy_db, mig)
    assert db.current_version(legacy_db) == 3
    assert db.fingerprint(legacy_db, list(before)) == before
    cols = {
        r[0]
        for r in legacy_db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='daily_metrics'"
        ).fetchall()
    }
    assert "battery_ran_out" in cols  # sigue la forma anterior
