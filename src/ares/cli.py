"""CLI de ARES · Bootstrap v0.5: init-db, secret, sync, doctor, stats, serve, whoop-auth."""

from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__, db, doctor, log, runner, serve
from .config import KNOWN_SECRETS, KeyringUnavailable, get_secret, load_settings, set_secret
from .connectors import whoop_oauth, whoop_tokens
from .locks import LockTimeout, file_lock


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
    try:
        if args.action == "set":
            value = getpass.getpass(f"Valor de {args.name} (no se mostrará): ").strip()
            if not value:
                print("Vacío: no se guarda nada.")
                return 1
            set_secret(args.name, value)
            print(f"{args.name} guardado en el almacén del sistema.")
        else:
            print(f"{args.name}: {'presente' if get_secret(args.name) else 'no configurado'}")
    except KeyringUnavailable as exc:
        print(str(exc))
        return 1
    return 0


SOURCE_LABELS = {
    "intervals": "intervals.icu",
    "tredict": "Tredict",
    "whoop": "WHOOP",
}


def cmd_sync(args: argparse.Namespace) -> int:
    s = load_settings()
    logger = log.setup(s.log_dir)
    conn = db.connect(s.db_path)
    try:
        pending = db.verify(conn, db.discover(s.migrations_dir))
        if pending:
            print("La base no está al día: ejecuta ares init-db")
            return 1
        try:
            res = runner.run_source_sync(conn, args.source, s, logger=logger, days=args.days)
        except runner.SyncSkipped as exc:
            print(str(exc))
            return 1
        except Exception as exc:
            print(f"Error: {exc}")
            return 1
        print(
            f"{SOURCE_LABELS[args.source]} · {res.fetched} recibidos · "
            f"{res.inserted} nuevos · {res.fetched - res.inserted} sin cambios"
            + (f" · {res.nights} noches recalculadas" if res.nights is not None else "")
            + (" · carga histórica" if res.history else "")
        )
    finally:
        conn.close()
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Carga histórica de WHOOP a mano (con el servicio parado: DuckDB admite un solo proceso)."""
    s = load_settings()
    days = args.days or s.whoop_history_days
    if days <= 0:
        print("--days debe ser positivo")
        return 1
    logger = log.setup(s.log_dir)
    conn = db.connect(s.db_path)
    try:
        if db.verify(conn, db.discover(s.migrations_dir)):
            print("La base no está al día: ejecuta ares init-db")
            return 1
        try:
            res = runner.run_source_sync(conn, "whoop", s, logger=logger, days=days)
        except runner.SyncSkipped as exc:
            print(str(exc))
            return 1
        except Exception as exc:
            print(f"Error: {exc}")
            return 1
        print(
            f"WHOOP · {days} días · {res.fetched} registros recibidos · {res.inserted} nuevos · "
            f"{res.nights} noches recalculadas"
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
            "FROM raw_payload WHERE source IN ('whoop', 'intervals', 'tredict') "
            "GROUP BY ALL ORDER BY ALL"
        ).fetchall()
        if not rows:
            print("Capa bruta vacía.")
        for src, ep, n, d0, d1 in rows:
            print(f"{src}/{ep}: {n} filas · {d0} → {d1}")
        runs = conn.execute(
            "SELECT job, status, started, git_commit FROM job_runs "
            "WHERE lower(job) NOT LIKE '%polar%' ORDER BY started DESC LIMIT 5"
        ).fetchall()
        if runs:
            print("\nÚltimas ejecuciones:")
            for job, status, started, commit in runs:
                print(f"  {started:%Y-%m-%d %H:%M} · {job} · {status} · {commit}")
    finally:
        conn.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    return serve.run(run_once=args.once)


def _ask_hidden(name: str, prompt: str) -> bool:
    """Pide un valor sin eco y lo guarda directamente en el almacén. Nunca por argumento,
    variable de entorno ni log."""
    value = getpass.getpass(prompt).strip()
    if not value:
        print("Vacío: no se guarda nada.")
        return False
    set_secret(name, value)
    return True


def cmd_whoop_auth(args: argparse.Namespace) -> int:
    s = load_settings()
    logger = log.setup(s.log_dir)
    try:
        if args.new_client or not get_secret("whoop_client_id"):
            if not _ask_hidden("whoop_client_id", "Client ID de WHOOP (no se mostrará): "):
                return 1
        if args.new_client or not get_secret("whoop_client_secret"):
            if not _ask_hidden("whoop_client_secret", "Client Secret de WHOOP (no se mostrará): "):
                return 1
        client_id = get_secret("whoop_client_id") or ""
        client_secret = get_secret("whoop_client_secret") or ""
    except KeyringUnavailable as exc:
        print(str(exc))
        return 1
    print(f"Redirección: {s.whoop_redirect_uri} (debe estar registrada exacta en el panel)")
    print(f"Permisos: {whoop_oauth.SCOPES}")
    print("Abriendo el navegador para autorizar ARES en WHOOP...")
    try:
        # El mismo bloqueo que la renovación: nadie renueva mientras se autoriza.
        with file_lock(whoop_tokens.lock_path(s.data_dir), timeout_s=10):
            tokens = whoop_oauth.authorize(client_id, client_secret, s.whoop_redirect_uri)
            whoop_tokens.save_tokens(tokens, set_secret)
    except LockTimeout as exc:
        print(f"Error: {exc}")
        return 1
    except whoop_oauth.OAuthError as exc:
        logger.warning("whoop_auth_error", fuente="whoop", http_status=exc.status, error=exc.error)
        print(f"Error: {exc}")
        return 1
    logger.info("whoop_auth_ok", fuente="whoop", expires_at=tokens.expires_at.isoformat())
    print(f"Autorizado. El token expira: {tokens.expires_at.isoformat()}")
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    import uvicorn  # solo hace falta aquí

    from .app.server import create_app

    s = load_settings()
    try:
        conn = db.connect_read_only(s.db_path)
    except FileNotFoundError as exc:
        print(str(exc))
        return 1
    except Exception as exc:  # p. ej. `ares serve` tiene la base abierta para escribir
        print(f"No se puede abrir la base en solo lectura: {exc}")
        return 1
    bind = args.bind or s.app_bind
    host, _, port = bind.rpartition(":")
    print(f"App de ARES en http://{host}:{port}  (solo lectura · Ctrl+C para salir)")
    try:
        uvicorn.run(create_app(lambda: conn, s), host=host, port=int(port), log_level="warning")
    finally:
        conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ares", description="ARES Physiology · Bootstrap v0.5")
    p.add_argument("--version", action="version", version=f"ares {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="crea la base y aplica migraciones").set_defaults(
        func=cmd_init_db
    )

    ps = sub.add_parser("secret", help="guarda o comprueba un secreto (nunca lo muestra)")
    ps.add_argument("action", choices=["set", "check"])
    ps.add_argument("name", choices=KNOWN_SECRETS)
    ps.set_defaults(func=cmd_secret)

    py = sub.add_parser("sync", help="sincroniza una fuente (manual, fuera del planificador)")
    py.add_argument("source", choices=["intervals", "tredict", "whoop"])
    py.add_argument(
        "--days",
        type=int,
        default=None,
        help="por defecto: incremental (3 d) o backfill si hace falta",
    )
    py.set_defaults(func=cmd_sync)

    pb = sub.add_parser(
        "backfill",
        help="carga histórica de WHOOP en la capa bruta y noches recalculadas (servicio parado)",
    )
    pb.add_argument("source", choices=["whoop"])
    pb.add_argument("--days", type=int, default=None, help="por defecto WHOOP_HISTORY_DAYS")
    pb.set_defaults(func=cmd_backfill)

    pd = sub.add_parser("doctor", help="comprueba Python, base, secretos, configuración y red")
    pd.add_argument("--offline", action="store_true")
    pd.set_defaults(func=cmd_doctor)

    sub.add_parser("stats", help="resumen de la capa bruta y últimas ejecuciones").set_defaults(
        func=cmd_stats
    )

    pv = sub.add_parser("serve", help="proceso único: base + planificador interno")
    pv.add_argument(
        "--once", action="store_true", help="una pasada de sincronización y salir (para pruebas)"
    )
    pv.set_defaults(func=cmd_serve)

    pw = sub.add_parser(
        "whoop-auth",
        help="autorización OAuth inicial con WHOOP (una sola vez; pide el cliente sin eco)",
    )
    pw.add_argument(
        "--new-client",
        action="store_true",
        help="vuelve a pedir Client ID y Client Secret aunque ya estén guardados",
    )
    pw.set_defaults(func=cmd_whoop_auth)

    pa = sub.add_parser(
        "app", help="app local (Inicio, Progreso, Lab) sobre tus datos reales; solo lectura"
    )
    pa.add_argument("--bind", help="host:puerto (por defecto APP_BIND o 127.0.0.1:8443)")
    pa.set_defaults(func=cmd_app)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except db.DatabaseBusy as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
