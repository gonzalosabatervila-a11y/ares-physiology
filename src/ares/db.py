"""Conexión única a DuckDB y migraciones numeradas con registro verificado en schema_version."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

MIGRATION_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")

SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  name VARCHAR NOT NULL,
  sha256 VARCHAR NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL
);
"""


class MigrationError(RuntimeError):
    pass


class DatabaseBusy(RuntimeError):
    """Otro proceso tiene la base abierta (DuckDB solo admite uno)."""


# El texto del aviso depende del sistema y del idioma: en Windows español llega en español
# («...utilizado por otro proceso»). DuckDB añade siempre, en inglés, «File is already open in ...
# (PID n)» o «Conflicting lock ... (PID n)», y eso es lo que no cambia con el idioma.
_BUSY_HINTS = (
    "lock",
    "already open",
    "another process",
    "otro proceso",
    "(pid",
)


def _open(path: Path, **kw: object) -> duckdb.DuckDBPyConnection:
    try:
        return duckdb.connect(str(path), **kw)  # type: ignore[arg-type]
    except duckdb.IOException as exc:
        if any(h in str(exc).lower() for h in _BUSY_HINTS):
            raise DatabaseBusy(
                "La base de datos está abierta por otro proceso: normalmente el servicio ARES "
                "(`ares serve`). Usa la app, o para el servicio con `nssm stop ARESPhysiology`."
            ) from exc
        raise


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def sha256(self) -> str:
        """Huella canónica: los saltos de línea se normalizan a LF, así que es la misma en
        Mac, Linux y Windows (Git en Windows convierte a CRLF al clonar)."""
        return _sha(_lf(self.path.read_bytes()))

    def accepted_hashes(self) -> set[str]:
        """Huellas válidas para una base ya creada: la canónica, la de los bytes tal cual y la
        variante CRLF. Una base creada desde un clon de Windows guardó la de CRLF."""
        raw = self.path.read_bytes()
        lf = _lf(raw)
        return {_sha(raw), _sha(lf), _sha(lf.replace(b"\n", b"\r\n"))}


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return _open(db_path)


def connect_read_only(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Solo lectura, para la app en desarrollo. Falla si otro proceso (ares serve)
    tiene la base abierta para escribir: en producción la app vive dentro de ese proceso."""
    if not db_path.exists():
        raise FileNotFoundError(f"No existe {db_path}: ejecuta ares init-db")
    return _open(db_path, read_only=True)


def discover(migrations_dir: Path) -> list[Migration]:
    found = []
    for p in sorted(migrations_dir.glob("*.sql")):
        m = MIGRATION_RE.match(p.name)
        if not m:
            raise MigrationError(f"Nombre de migración inválido: {p.name}")
        found.append(Migration(int(m.group(1)), m.group(2), p))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"Migraciones no consecutivas desde 001: {versions}")
    return found


def applied(conn: duckdb.DuckDBPyConnection) -> dict[int, tuple[str, str]]:
    conn.execute(SCHEMA_VERSION_DDL)
    rows = conn.execute(
        "SELECT version, name, sha256 FROM schema_version ORDER BY version"
    ).fetchall()
    return {v: (n, h) for v, n, h in rows}


def verify(conn: duckdb.DuckDBPyConnection, migrations: list[Migration]) -> list[Migration]:
    """Comprueba que lo aplicado coincide con los ficheros; devuelve las pendientes."""
    done = applied(conn)
    by_version = {m.version: m for m in migrations}
    for v, (name, sha) in done.items():
        m = by_version.get(v)
        if m is None:
            raise MigrationError(
                f"La base tiene la migración {v:03d} ({name}) y no existe el fichero"
            )
        if sha not in m.accepted_hashes():
            raise MigrationError(
                f"La migración {v:03d}_{m.name}.sql ha cambiado tras aplicarse. "
                "Las migraciones aplicadas no se editan: crea una nueva."
            )
    if done and sorted(done) != list(range(1, max(done) + 1)):
        raise MigrationError(f"Huecos en schema_version: {sorted(done)}")
    return [m for m in migrations if m.version not in done]


def migrate(conn: duckdb.DuckDBPyConnection, migrations_dir: Path) -> list[int]:
    pending = verify(conn, discover(migrations_dir))
    for m in pending:
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(m.sql)
            conn.execute(
                "INSERT INTO schema_version VALUES (?, ?, ?, now())",
                [m.version, m.name, m.sha256],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return [m.version for m in pending]


def current_version(conn: duckdb.DuckDBPyConnection) -> int:
    done = applied(conn)
    return max(done) if done else 0
