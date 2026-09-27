"""CLI de ARES · Bootstrap v0.1: init-db, secret, sync intervals, doctor, stats."""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__, db, doctor, jobs, log
from .config import KNOWN_SECRETS, get_secret, load_settings, set_secret
from .connectors.base import HttpClient
from .connectors.intervals import sync_wellness


def cmd_init_db(args: argparse.Namespace) -> int:
    s = load_settings()
    conn = db.connect(s.db_path)
    try:
        done = db.migrate(conn, s.migrations_dir)
        print(f"Base: {s.db_path}")
        print(f"Migraciones aplicadas ahora: {done or 'ninguna (ya estaba al día)'}")
        print(f"schema_version: {db.current_version(conn)}")
    finally:
        conn.close()
    return 0


def cmd_secret(args: argparse.Namespace) -> int:
    if args.action == "set":
        value = getpass.getpass(f"Valor de {args.name} (no se mostrará): ").strip()
        if not value:
            print("Vacío: no se guarda nada.")
            return 1
        set_secret(args.name, value)
        print(f"{args.name} guardado en el almacén del sistema.")
    else:
        print(f"{args.name}: {'presente' if get_secret(args.name) else 'no configurado'}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    s = load_settings()
    logger = log.setup(s.log_dir)
    key = get_secret("intervals_api_key")
    if not key:
        print("Falta la clave: ares secret set intervals_api_key")
        return 1
    conn = db.connect(s.db_path)
    try:
        pending = db.verify(conn, db.discover(s.migrations_dir))
        if pending:
            print("La base no está al día: ejecuta ares init-db")
            return 1
        run_id = jobs.start(conn, "sync_intervals", s.rules_version)
        try:
            res = sync_wellness(conn, HttpClient(), key, s.intervals_athlete_id, args.days)
        except Exception as exc:
            jobs.finish(conn, run_id, "error", {"error": str(exc)})
            logger.error("sync_failed", source="intervals", endpoint="wellness", error=str(exc))
            print(f"Error: {exc}")
            return 1
        detail = {"days": args.days, "fetched": res.fetched, "inserted": res.inserted}
        jobs.finish(conn, run_id, "ok", detail)
        logger.info("sync_ok", source="intervals", endpoint="wellness", **detail)
        print(
            f"intervals.icu · {res.fetched} días recibidos · {res.inserted} nuevos · "
            f"{res.unchanged} sin cambios"
        )
    finally:
        conn.close()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = doctor.run(load_settings(), offline=args.offline)
    print(f"ARES {__version__} · doctor\n")
    print(doctor.render(checks))
    return 0 if all(c.ok for c in checks) else 1


def cmd_stats(args: argparse.Namespace) -> int:
    s = load_settings()
    conn = db.connect(s.db_path)
    try:
        print(f"schema_version: {db.current_version(conn)}\n")
        rows = conn.execute(
            "SELECT source, endpoint, count(*) AS n, min(day), max(day) "
            "FROM raw_payload GROUP BY ALL ORDER BY ALL"
        ).fetchall()
        if not rows:
            print("Capa bruta vacía.")
        for src, ep, n, d0, d1 in rows:
            print(f"{src}/{ep}: {n} filas · {d0} → {d1}")
        runs = conn.execute(
            "SELECT job, status, started, git_commit FROM job_runs ORDER BY started DESC LIMIT 5"
        ).fetchall()
        if runs:
            print("\nÚltimas ejecuciones:")
            for job, status, started, commit in runs:
                print(f"  {started:%Y-%m-%d %H:%M} · {job} · {status} · {commit}")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ares", description="ARES Physiology · Bootstrap v0.1")
    p.add_argument("--version", action="version", version=f"ares {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="crea la base y aplica migraciones").set_defaults(
        func=cmd_init_db
    )

    ps = sub.add_parser("secret", help="guarda o comprueba un secreto (nunca lo muestra)")
    ps.add_argument("action", choices=["set", "check"])
    ps.add_argument("name", choices=KNOWN_SECRETS)
    ps.set_defaults(func=cmd_secret)

    py = sub.add_parser("sync", help="sincroniza una fuente")
    py.add_argument("source", choices=["intervals"])
    py.add_argument("--days", type=int, default=3)
    py.set_defaults(func=cmd_sync)

    pd = sub.add_parser("doctor", help="comprueba Python, base, secretos, configuración y red")
    pd.add_argument("--offline", action="store_true")
    pd.set_defaults(func=cmd_doctor)

    sub.add_parser("stats", help="resumen de la capa bruta y últimas ejecuciones").set_defaults(
        func=cmd_stats
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
