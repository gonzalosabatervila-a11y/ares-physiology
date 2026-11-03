"""One-time, non-printing Mac -> Linux ARES migration bundle.

Requires: stop the Mac launchd daemon before running; run from the Mac Keychain
environment. Produces only an encrypted token vault, key and closed DuckDB copy.
The bundle directory must be transferred over SSH and kept private.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

from cryptography.fernet import Fernet

from ares import db
from ares.config import (
    KNOWN_SECRETS, _write_vault, get_secret, load_settings,
)

REQUIRED = (
    "intervals_api_key", "tredict_token",
    "whoop_client_id", "whoop_client_secret",
    "whoop_access_token", "whoop_refresh_token", "whoop_token_expiry",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta ARES cifrado para OVH")
    parser.add_argument("destination", type=Path, help="Carpeta NUEVA y privada (no existente)")
    args = parser.parse_args()
    if os.getenv("ARES_SECRETS_FILE"):
        print("ERROR: exporta desde el Llavero de macOS, no desde el almacén Linux.")
        return 1
    # Read non-secret runtime settings from the original working installation,
    # while running the tested exporter from the newer checkout.
    origin_env = Path.home() / "ares" / ".env"
    settings = load_settings(origin_env if origin_env.is_file() else None)
    if not settings.db_path.is_file():
        print("ERROR: no encuentro la base de ARES.")
        return 1

    # A live ares serve owns DuckDB. Require a closed, valid DB before exporting.
    try:
        conn = db.connect_read_only(settings.db_path)
        try:
            pending = db.verify(conn, db.discover(settings.migrations_dir))
            if pending:
                print("ERROR: hay migraciones pendientes; verifica primero el esquema.")
                return 1
            count = conn.execute("SELECT count(*) FROM raw_payload").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:
        print(f"ERROR: base ocupada o no verificable: {type(exc).__name__}. "
              "Detén primero ares serve en el Mac.")
        return 1

    secrets: dict[str, str] = {}
    for name in KNOWN_SECRETS:
        secret = get_secret(name)
        if secret:
            secrets[name] = secret
    missing = [name for name in REQUIRED if not secrets.get(name)]
    if missing:
        print("ERROR: credenciales ausentes: " + ", ".join(missing))
        return 1

    dest: Path = args.destination.expanduser().resolve()
    dest.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(dest, 0o700)
    key_path = dest / "ares.key"
    key_path.write_bytes(Fernet.generate_key() + b"\n")
    os.chmod(key_path, 0o600)
    vault = dest / "secrets.enc"
    # _write_vault derives its key from the export file without displaying it.
    os.environ["ARES_SECRETS_KEY_FILE"] = str(key_path)
    _write_vault(vault, secrets)
    source_db = settings.db_path
    copied_db = dest / "ares.duckdb"
    shutil.copyfile(source_db, copied_db)
    os.chmod(copied_db, 0o600)
    # The reviewed training plan is mutable user state, not embedded in DuckDB.
    # Include the snapshot if present, with a strict type/size check. The VPS
    # server will otherwise use its reference plan, silently losing overrides.
    plan = settings.data_dir / "training_plan.json"
    if plan.exists():
        if not plan.is_file() or plan.is_symlink() or plan.stat().st_size > 2_000_000:
            raise RuntimeError("training_plan.json no es un archivo regular de tamaño aceptable")
        output_plan = dest / "training_plan.json"
        shutil.copyfile(plan, output_plan)
        os.chmod(output_plan, 0o600)
    # Preserve verified, non-secret source/device configuration: without this
    # Intervals can silently fall back to athlete ID 0 on Linux.
    runtime = {
        "ARES_DEVICE_ID": settings.device_id,
        "INTERVALS_ATHLETE_ID": settings.intervals_athlete_id,
        "BACKFILL_MAX_DAYS": str(settings.backfill_max_days),
        "ARES_RULES_VERSION": settings.rules_version,
        "INTERVALS_WELLNESS_DEVICE": settings.intervals_wellness_device,
        "ARES_ALGO_VERSION": settings.algo_version,
        "WHOOP_HISTORY_DAYS": str(settings.whoop_history_days),
        "PHYSIOLOGY_PROVIDER": settings.physiology_provider,
    }
    if settings.nutrition_weight_kg is not None:
        runtime["ARES_NUTRITION_WEIGHT_KG"] = str(settings.nutrition_weight_kg)
    if any(
        "\\n" in value or "\\r" in value or "\\x00" in value or "#" in value
        for value in runtime.values()
    ):
        raise RuntimeError("Configuración ARES no transportable como entorno Docker")
    runtime_file = dest / "ares.runtime.env"
    runtime_file.write_text(
        "".join(f"{name}={value}\\n" for name, value in runtime.items()),
        encoding="utf-8",
    )
    os.chmod(runtime_file, 0o600)
    if settings.intervals_athlete_id == "0":
        print("AVISO: INTERVALS_ATHLETE_ID=0; antes de arrancar OVH debe corregirse.")
    digest = hashlib.sha256(copied_db.read_bytes()).hexdigest()
    print(f"ARES exportado: {count} filas brutas, {len(secrets)} credenciales cifradas.")
    print(f"Directorio privado: {dest}")
    print(f"SHA256 DB: {digest}")
    print("No compartas estos archivos ni la clave. Importa ambos al servidor por SSH.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
