"""ares doctor con red simulada y secretos inyectados (nunca toca el llavero real)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from ares import db, doctor


def test_doctor_todo_correcto_con_base_migrada_y_clave(settings, monkeypatch):
    c = db.connect(settings.db_path)
    db.migrate(c, settings.migrations_dir)
    c.close()
    monkeypatch.setattr(doctor, "keyring_backend_name", lambda: "keyring.backends.macOS.Keyring")
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    checks = doctor.run(
        settings,
        secret_getter=lambda n: expiry if n == "whoop_token_expiry" else "k",
        http=http,
    )
    assert all(c.ok for c in checks), doctor.render(checks)


def test_doctor_detecta_base_sin_migrar_y_falta_de_clave(settings, monkeypatch):
    monkeypatch.setattr(doctor, "keyring_backend_name", lambda: "keyring.backends.macOS.Keyring")
    checks = {c.name: c for c in doctor.run(settings, offline=True, secret_getter=lambda n: None)}
    assert not checks["Base de datos"].ok and "init-db" in checks["Base de datos"].detail
    assert not checks["Secreto intervals_api_key"].ok
    assert not checks["Secreto tredict_token"].ok


def test_doctor_sin_autorizacion_de_whoop_pide_whoop_auth(settings, monkeypatch):
    monkeypatch.setattr(doctor, "keyring_backend_name", lambda: "keyring.backends.macOS.Keyring")
    checks = {c.name: c for c in doctor.run(settings, secret_getter=lambda n: None)}
    assert not checks["Cliente WHOOP"].ok and "whoop-auth" in checks["Cliente WHOOP"].detail
    assert not checks["Red · WHOOP"].ok


def test_doctor_whoop_llama_a_cycle_con_el_token_y_no_lo_muestra(settings, monkeypatch):
    monkeypatch.setattr(doctor, "keyring_backend_name", lambda: "keyring.backends.macOS.Keyring")
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"records": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    expiry = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    secrets = {
        "whoop_client_id": "cid",
        "whoop_client_secret": "csec",
        "whoop_access_token": "acc-secreto",
        "whoop_refresh_token": "ref",
        "whoop_token_expiry": expiry,
    }
    checks = {c.name: c for c in doctor.run(settings, secret_getter=secrets.get, http=http)}
    assert checks["Red · WHOOP"].ok
    (req,) = [r for r in seen if "whoop" in str(r.url)]
    assert str(req.url) == "https://api.prod.whoop.com/developer/v2/cycle?limit=1"
    assert req.headers["Authorization"] == "Bearer acc-secreto"
    assert "acc-secreto" not in doctor.render(list(checks.values()))
