"""Regression checks for the VPS vault and the private Gonzalo OS bridge."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ares import config
from ares.app.server import create_app


def test_encrypted_vault_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_path = tmp_path / "ares.key"
    key_path.write_bytes(Fernet.generate_key())
    os.chmod(key_path, 0o600)
    vault = tmp_path / "secrets.enc"
    monkeypatch.setenv("ARES_SECRETS_FILE", str(vault))
    monkeypatch.setenv("ARES_SECRETS_KEY_FILE", str(key_path))
    monkeypatch.delenv("ARES_SECRETS_KEY", raising=False)
    config.set_secret("whoop_refresh_token", "rotated-test-token")
    config.set_secret("intervals_api_key", "intervals-test")
    assert config.get_secret("whoop_refresh_token") == "rotated-test-token"
    assert config.get_secret("intervals_api_key") == "intervals-test"
    assert b"rotated-test-token" not in vault.read_bytes()
    assert vault.stat().st_mode & 0o777 == 0o600


def test_vault_wrong_key_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_path = tmp_path / "ares.key"
    key_path.write_bytes(Fernet.generate_key())
    vault = tmp_path / "secrets.enc"
    monkeypatch.setenv("ARES_SECRETS_FILE", str(vault))
    monkeypatch.setenv("ARES_SECRETS_KEY_FILE", str(key_path))
    monkeypatch.delenv("ARES_SECRETS_KEY", raising=False)
    config.set_secret("tredict_token", "test")
    key_path.write_bytes(Fernet.generate_key())
    with pytest.raises(config.KeyringUnavailable):
        config.get_secret("tredict_token")


def test_production_bridge_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARES_PRODUCTION", "1")
    monkeypatch.setenv("ARES_BRIDGE_SECRET", "x" * 48)
    app = create_app(lambda: None, config.load_settings(), auto_sync=False)
    with TestClient(app) as client:
        assert client.get("/static/app.js").status_code == 403
        assert client.get("/static/app.js", headers={"x-ares-bridge-secret": "wrong"}).status_code == 403
        ok = client.get("/static/app.js", headers={"x-ares-bridge-secret": "x" * 48})
        assert ok.status_code == 200
        assert b"Scientific" in ok.content or b"route" in ok.content


def test_production_no_bridge_secret_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARES_PRODUCTION", "1")
    monkeypatch.delenv("ARES_BRIDGE_SECRET", raising=False)
    app = create_app(lambda: None, config.load_settings(), auto_sync=False)
    with TestClient(app) as client:
        assert client.get("/").status_code == 503
