"""`ares whoop-auth`: el cliente se pide sin eco y va directo al almacén; ni el secreto ni los
tokens llegan a la salida ni al log; el error de WHOOP se registra con su código HTTP."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from ares import cli
from ares.config import get_secret, set_secret
from ares.connectors import whoop_oauth

SECRETO = "csec-super-secreto"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("ares.log._configured", False)
    return tmp_path


def fake_authorize(seen: list):
    def authorize(client_id, client_secret, redirect_uri, **kw):
        seen.append((client_id, client_secret, redirect_uri))
        return whoop_oauth.TokenSet("acc-1", "ref-1", datetime.now(UTC) + timedelta(hours=1))

    return authorize


def test_pide_el_cliente_sin_eco_y_lo_guarda_en_el_almacen(entorno, monkeypatch, capsys, caplog):
    caplog.set_level(logging.INFO)
    respuestas = iter(["cid-1", SECRETO])
    prompts: list[str] = []

    def getpass(prompt: str) -> str:
        prompts.append(prompt)
        return next(respuestas)

    seen: list = []
    monkeypatch.setattr("ares.cli.getpass.getpass", getpass)
    monkeypatch.setattr("ares.cli.whoop_oauth.authorize", fake_authorize(seen))

    assert cli.main(["whoop-auth"]) == 0
    assert len(prompts) == 2 and "Secret" in prompts[1]
    assert seen == [("cid-1", SECRETO, "http://localhost:8765/callback")]
    assert get_secret("whoop_client_secret") == SECRETO
    assert get_secret("whoop_refresh_token") == "ref-1"
    out = capsys.readouterr()
    assert "whoop_auth_ok" in caplog.text
    for texto in (out.out, out.err, caplog.text):
        assert SECRETO not in texto and "acc-1" not in texto and "ref-1" not in texto


def test_con_el_cliente_ya_guardado_no_lo_vuelve_a_pedir(entorno, monkeypatch):
    set_secret("whoop_client_id", "cid-1")
    set_secret("whoop_client_secret", SECRETO)
    monkeypatch.setattr("ares.cli.getpass.getpass", lambda p: pytest.fail("no debía preguntar"))
    monkeypatch.setattr("ares.cli.whoop_oauth.authorize", fake_authorize([]))
    assert cli.main(["whoop-auth"]) == 0


def test_new_client_vuelve_a_pedirlo(entorno, monkeypatch):
    set_secret("whoop_client_id", "viejo")
    set_secret("whoop_client_secret", "viejo")
    respuestas = iter(["cid-2", "csec-2"])
    monkeypatch.setattr("ares.cli.getpass.getpass", lambda p: next(respuestas))
    seen: list = []
    monkeypatch.setattr("ares.cli.whoop_oauth.authorize", fake_authorize(seen))
    assert cli.main(["whoop-auth", "--new-client"]) == 0
    assert seen[0][:2] == ("cid-2", "csec-2")


def test_el_secreto_no_se_acepta_por_argumento(entorno):
    with pytest.raises(SystemExit):
        cli.main(["whoop-auth", "--client-secret", SECRETO])


def test_un_rechazo_de_whoop_se_registra_con_su_codigo_y_sin_secretos(entorno, monkeypatch, caplog):
    set_secret("whoop_client_id", "cid-1")
    set_secret("whoop_client_secret", SECRETO)

    def authorize(*a, **kw):
        raise whoop_oauth.OAuthError(
            "Canje del código fallida: HTTP 401 · invalid_client",
            status=401,
            error="invalid_client",
        )

    monkeypatch.setattr("ares.cli.whoop_oauth.authorize", authorize)
    assert cli.main(["whoop-auth"]) == 1
    assert '"http_status": 401' in caplog.text and "invalid_client" in caplog.text
    assert SECRETO not in caplog.text
    assert get_secret("whoop_access_token") is None
