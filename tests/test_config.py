"""Configuración del proveedor fisiológico: PHYSIOLOGY_PROVIDER y ARES_DEVICE_ID van separados
(proveedor activo frente a identidad de la unidad), con valores por defecto seguros."""

from __future__ import annotations

import pytest

from ares.config import KNOWN_SECRETS, load_settings, set_secret

VARS = (
    "PHYSIOLOGY_PROVIDER",
    "ARES_DEVICE_ID",
    "ARES_ALGO_VERSION",
    "WHOOP_REDIRECT_URI",
    "WHOOP_HISTORY_DAYS",
)


@pytest.fixture
def entorno_limpio(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_DATA_DIR", str(tmp_path))
    for var in VARS:
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "no-existe.env"


def test_valores_por_defecto_del_proveedor(entorno_limpio):
    cfg = load_settings(env_file=entorno_limpio)
    assert cfg.physiology_provider == "whoop"
    assert cfg.device_id == "pulsera-principal"
    assert cfg.algo_version == "whoop-1"
    assert cfg.whoop_redirect_uri == "http://localhost:8765/callback"
    assert cfg.whoop_history_days == 90


def test_proveedor_y_unidad_se_leen_por_separado(entorno_limpio, monkeypatch):
    monkeypatch.setenv("PHYSIOLOGY_PROVIDER", " WHOOP  # comentario")
    monkeypatch.setenv("ARES_DEVICE_ID", "pulsera-repuesto")
    monkeypatch.setenv("WHOOP_HISTORY_DAYS", "120")
    cfg = load_settings(env_file=entorno_limpio)
    assert (cfg.physiology_provider, cfg.device_id) == ("whoop", "pulsera-repuesto")
    assert cfg.whoop_history_days == 120


def test_un_proveedor_desconocido_no_arranca(entorno_limpio, monkeypatch):
    monkeypatch.setenv("PHYSIOLOGY_PROVIDER", "oura")
    with pytest.raises(ValueError, match="PHYSIOLOGY_PROVIDER"):
        load_settings(env_file=entorno_limpio)


@pytest.mark.parametrize("dias", ["0", "-5"])
def test_la_carga_historica_exige_dias_positivos(entorno_limpio, monkeypatch, dias):
    monkeypatch.setenv("WHOOP_HISTORY_DAYS", dias)
    with pytest.raises(ValueError, match="WHOOP_HISTORY_DAYS"):
        load_settings(env_file=entorno_limpio)


def test_los_secretos_de_whoop_son_conocidos():
    for name in (
        "whoop_client_id",
        "whoop_client_secret",
        "whoop_access_token",
        "whoop_refresh_token",
        "whoop_token_expiry",
    ):
        assert name in KNOWN_SECRETS
        set_secret(name, "x")  # el llavero está aislado en conftest
