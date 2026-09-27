"""ares doctor con red simulada y secretos inyectados (nunca toca el llavero real)."""

from __future__ import annotations

import httpx

from ares import db, doctor


def test_doctor_todo_correcto_con_base_migrada_y_clave(settings, monkeypatch):
    c = db.connect(settings.db_path)
    db.migrate(c, settings.migrations_dir)
    c.close()
    monkeypatch.setattr(doctor, "keyring_backend_name", lambda: "keyring.backends.macOS.Keyring")
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    checks = doctor.run(settings, secret_getter=lambda n: "k", http=http)
    assert all(c.ok for c in checks), doctor.render(checks)


def test_doctor_detecta_base_sin_migrar_y_falta_de_clave(settings, monkeypatch):
    monkeypatch.setattr(doctor, "keyring_backend_name", lambda: "keyring.backends.macOS.Keyring")
    checks = {c.name: c for c in doctor.run(settings, offline=True, secret_getter=lambda n: None)}
    assert not checks["Base de datos"].ok and "init-db" in checks["Base de datos"].detail
    assert not checks["Secreto intervals_api_key"].ok
