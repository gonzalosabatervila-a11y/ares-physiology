"""CLI de ARES · Bootstrap v0.5: init-db, secret, sync, doctor, stats, serve, polar-auth."""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from . import __version__, db, doctor, log, polar_night, runner, serve
from .config import KNOWN_SECRETS, KeyringUnavailable, get_secret, load_settings, set_secret
from .connectors import polar_oauth, polar_probe, polar_tokens


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


SOURCE_LABELS = {"intervals": "intervals.icu", "tredict": "Tredict", "polar": "Polar"}


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
            + (f" · {res.ppi_rows} PPI nuevos" if res.ppi_rows is not None else "")
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


def cmd_serve(args: argparse.Namespace) -> int:
    return serve.run(run_once=args.once)


def cmd_polar_auth(args: argparse.Namespace) -> int:
    s = load_settings()
    try:
        client_id = get_secret("polar_client_id")
        client_secret = get_secret("polar_client_secret")
    except KeyringUnavailable as exc:
        print(str(exc))
        return 1
    if not client_id or not client_secret:
        print(
            "Faltan las credenciales del cliente. Créalo en admin.polaraccesslink.com "
            f"con redirect_uri = {s.polar_redirect_uri}, luego:\n"
            "  ares secret set polar_client_id\n"
            "  ares secret set polar_client_secret"
        )
        return 1
    print("Abriendo el navegador para autorizar ARES en Polar Flow...")
    try:
        tokens = polar_oauth.authorize(client_id, client_secret, s.polar_redirect_uri)
    except polar_oauth.OAuthError as exc:
        print(f"Error: {exc}")
        return 1
    set_secret("polar_access_token", tokens.access_token)
    set_secret("polar_refresh_token", tokens.refresh_token)
    set_secret("polar_token_expiry", tokens.expires_at.isoformat())
    print(f"Autorizado. El token expira: {tokens.expires_at.isoformat()}")
    return 0


def cmd_polar_probe(args: argparse.Namespace) -> int:
    s = load_settings()
    try:
        token = polar_tokens.get_access_token()
    except (KeyringUnavailable, polar_tokens.TokenError, polar_oauth.OAuthError) as exc:
        print(f"Error: {exc}")
        return 1
    day = date.fromisoformat(args.day) if args.day else datetime.now(ZoneInfo(s.tz)).date()
    out_dir = s.data_dir / "probe" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = polar_probe.run_probe(token, day, out_dir)
    print(f"Sonda de Polar v4 · día {day} · solo lectura, no escribe en la base\n")
    print(polar_probe.render(results, out_dir))
    return 0 if any(r.status == 200 for r in results) else 1


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


def cmd_polar_night(args: argparse.Namespace) -> int:
    s = load_settings()
    tz = ZoneInfo(s.tz)
    day = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    try:
        report = polar_night.night_report(s.data_dir / "probe", day, tz)
    except polar_night.NightError as exc:
        print(str(exc))
        return 1
    print(polar_night.render(report))
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
    py.add_argument("source", choices=["intervals", "tredict", "polar"])
    py.add_argument(
        "--days",
        type=int,
        default=None,
        help="por defecto: incremental (3 d) o backfill si hace falta",
    )
    py.set_defaults(func=cmd_sync)

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

    sub.add_parser(
        "polar-auth", help="autorización OAuth inicial con Polar (una sola vez)"
    ).set_defaults(func=cmd_polar_auth)

    pp = sub.add_parser(
        "polar-probe",
        help="primera llamada real a Polar: enseña la estructura de lo que devuelve (solo lectura)",
    )
    pp.add_argument("--day", help="día a sondear (AAAA-MM-DD); por defecto, hoy")
    pp.set_defaults(func=cmd_polar_probe)

    pa = sub.add_parser(
        "app", help="app local (Inicio, Progreso, Lab) sobre tus datos reales; solo lectura"
    )
    pa.add_argument("--bind", help="host:puerto (por defecto APP_BIND o 127.0.0.1:8443)")
    pa.set_defaults(func=cmd_app)

    pn = sub.add_parser(
        "polar-night",
        help="analiza una noche de la Loop con los ficheros de la sonda (solo lectura)",
    )
    pn.add_argument("--date", help="fecha del despertar (AAAA-MM-DD); por defecto, hoy")
    pn.set_defaults(func=cmd_polar_night)
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
