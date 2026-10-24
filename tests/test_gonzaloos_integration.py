"""Integration contract for the private GonzaloOS reverse proxy."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from ares import config
from ares.app.server import create_app
from ares.config import Settings


def _proxy_settings(settings: Settings) -> Settings:
    values = dict(settings.__dict__)
    values.update(public_base_path="/ares", proxy_auth_required=True)
    return Settings(**values)


def test_browser_assets_and_api_calls_are_prefix_relative(conn, settings):
    client = TestClient(create_app(lambda: conn, settings))
    html = client.get("/").text
    app_js = client.get("/static/app.js").text
    lab_js = client.get("/static/lab_ui.js").text
    manifest = json.loads(client.get("/static/manifest.webmanifest").text)

    assert 'href="static/' in html
    assert 'src="static/' in html
    assert 'href="/"' in html and "Volver a GonzaloOS" in html
    assert "'/api/" not in app_js and '"/api/' not in app_js and "`/api/" not in app_js
    prefixed_lab_js = lab_js.replace("'/api/auth/status'", "")
    assert "'/api/" not in prefixed_lab_js and '"/api/' not in prefixed_lab_js
    assert "`/api/" not in prefixed_lab_js
    assert "/api/auth/status" in lab_js
    assert "X-CSRF-Token" in lab_js
    assert manifest["start_url"] == "../#/laboratorio"
    assert manifest["scope"] == "../"
    assert all(not icon["src"].startswith("/") for icon in manifest["icons"])


def test_healthcheck_does_not_require_physiology_data(conn, settings):
    api = TestClient(create_app(lambda: conn, settings))
    assert api.get("/api/healthz").json() == {"ok": True}


def test_proxy_mode_write_requires_server_assertion_and_matching_csrf(conn, settings):
    api = TestClient(create_app(lambda: conn, _proxy_settings(settings), auto_sync=True))
    payload = {
        "event_type": "coffee",
        "occurred_at": "2026-10-24T09:00:00+02:00",
        "caffeine_mg": 80,
        "amount_basis": "estimated",
        "client_event_key": str(uuid4()),
    }
    base = {
        "Origin": "https://gonzaloos.es",
        "Host": "gonzaloos.es",
        "X-Ares-Lab": "1",
    }
    assert api.post("/api/lab/events", json=payload, headers=base).status_code == 403
    asserted = {**base, "X-Ares-Authorized": "1", "X-Ares-Csrf": "expected"}
    assert api.post("/api/lab/events", json=payload, headers=asserted).status_code == 403
    valid = {**asserted, "X-CSRF-Token": "expected"}
    assert api.post("/api/lab/events", json=payload, headers=valid).status_code == 201


def test_proxy_mode_rejects_insecure_or_cross_origin_write(conn, settings):
    api = TestClient(create_app(lambda: conn, _proxy_settings(settings), auto_sync=True))
    payload = {
        "event_type": "coffee",
        "occurred_at": "2026-10-24T09:00:00+02:00",
        "caffeine_mg": 80,
        "amount_basis": "estimated",
        "client_event_key": str(uuid4()),
    }
    headers = {
        "Host": "gonzaloos.es",
        "Origin": "https://evil.example",
        "X-Ares-Lab": "1",
        "X-Ares-Authorized": "1",
        "X-Ares-Csrf": "same",
        "X-CSRF-Token": "same",
    }
    assert api.post("/api/lab/events", json=payload, headers=headers).status_code == 403
    headers.update(Origin="http://gonzaloos.es")
    assert api.post("/api/lab/events", json=payload, headers=headers).status_code == 403


def test_container_reads_secret_files_without_logging_or_keyring(tmp_path, monkeypatch):
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "tredict_token").write_text("synthetic-token\n")
    monkeypatch.setenv("ARES_SECRETS_DIR", str(secret_dir))
    monkeypatch.setattr(config.keyring, "get_password", lambda *_: (_ for _ in ()).throw(
        AssertionError("keyring must not be called when a secret file exists")
    ))
    assert config.get_secret("tredict_token") == "synthetic-token"
    assert config.get_secret("unknown") is None


def test_container_persists_rotating_tokens_atomically(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    state_dir = tmp_path / "state"
    static_dir.mkdir()
    static_dir.joinpath("whoop_client_id").write_text("synthetic-client")
    monkeypatch.setenv("ARES_SECRETS_DIR", str(static_dir))
    monkeypatch.setenv("ARES_SECRET_STATE_DIR", str(state_dir))
    monkeypatch.setattr(config.keyring, "get_password", lambda *_: (_ for _ in ()).throw(
        AssertionError("container mode must not use keyring")
    ))
    monkeypatch.setattr(config.keyring, "set_password", lambda *_: (_ for _ in ()).throw(
        AssertionError("container mode must not use keyring")
    ))

    assert config.get_secret("whoop_client_id") == "synthetic-client"
    assert config.get_secret("whoop_access_token") is None
    config.set_secret("whoop_access_token", "rotated-synthetic-token")
    assert config.get_secret("whoop_access_token") == "rotated-synthetic-token"
    assert state_dir.joinpath("whoop_access_token").stat().st_mode & 0o777 == 0o600
    assert not list(state_dir.glob("*.tmp"))


def test_desktop_empty_secret_directory_still_falls_back_to_keyring(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_SECRETS_DIR", str(tmp_path / "empty-static"))
    monkeypatch.delenv("ARES_SECRET_STATE_DIR", raising=False)
    monkeypatch.setattr(
        config.keyring, "get_password",
        lambda service, name: "desktop-keyring-token" if name == "tredict_token" else None,
    )
    assert config.get_secret("tredict_token") == "desktop-keyring-token"


def test_container_contract_is_non_root_and_does_not_publish_ports():
    dockerfile = Path("Dockerfile").read_text()
    assert "USER ares" in dockerfile
    assert 'CMD ["ares","serve"]' in dockerfile
    assert "COPY . ." not in dockerfile
    assert "EXPOSE 8443" in dockerfile
