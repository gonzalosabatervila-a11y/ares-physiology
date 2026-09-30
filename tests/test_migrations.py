"""schema_version: qué migraciones se han aplicado, con hash verificado desde el primer día."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import duckdb
import pytest

from ares import db

EXPECTED = {1: "raw", 2: "core", 3: "decisions"}


def test_schema_version_registra_las_tres_migraciones_con_hash(conn, settings):
    rows = conn.execute(
        "SELECT version, name, sha256 FROM schema_version ORDER BY version"
    ).fetchall()
    assert [(v, n) for v, n, _ in rows] == sorted(EXPECTED.items())
    for v, _, sha in rows:
        path = next(settings.migrations_dir.glob(f"{v:03d}_*.sql"))
        assert sha == hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert db.current_version(conn) == 3


def test_migrar_dos_veces_no_hace_nada(conn, settings):
    assert db.migrate(conn, settings.migrations_dir) == []
    assert conn.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 3


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
