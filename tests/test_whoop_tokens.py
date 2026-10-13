"""Gestor del token de WHOOP: margen de 5 min, par rotado guardado antes de usarse, un solo
reintento ante 401 y renovaciones simultáneas (hilos y procesos) serializadas.

El servidor de token simulado se comporta como WHOOP: cada refresh token vale una sola vez;
reutilizarlo devuelve 400 invalid_grant."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest

from ares.config import REPO_ROOT
from ares.connectors import whoop_tokens

NOW = datetime(2026, 10, 2, 7, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


def store(**overrides: str) -> dict[str, str]:
    base = {
        "whoop_client_id": "cid",
        "whoop_client_secret": "csec",
        "whoop_access_token": "acc-0",
        "whoop_refresh_token": "ref-0",
        "whoop_token_expiry": (NOW + timedelta(minutes=50)).isoformat(),
    }
    base.update(overrides)
    return base


class FakeWhoop:
    """Endpoint de token de un solo uso, seguro entre hilos."""

    def __init__(self, valid: str = "ref-0", delay_s: float = 0.0) -> None:
        self.valid = valid
        self.n = 0
        self.delay_s = delay_s
        self.calls = 0
        self._mutex = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        with self._mutex:
            self.calls += 1
            if form.get("refresh_token") != self.valid:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.n += 1
            self.valid = f"ref-{self.n}"
            n = self.n
        time.sleep(self.delay_s)
        return httpx.Response(
            200,
            json={"access_token": f"acc-{n}", "refresh_token": f"ref-{n}", "expires_in": 3600},
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def call(tmp_path: Path, secrets: dict[str, str], fake: FakeWhoop, **kw) -> str:
    return whoop_tokens.get_access_token(
        tmp_path,
        http=fake.client(),
        secret_getter=secrets.get,
        secret_setter=secrets.__setitem__,
        now=clock,
        **kw,
    )


def test_token_vigente_no_renueva(tmp_path):
    fake = FakeWhoop()
    assert call(tmp_path, store(), fake) == "acc-0"
    assert fake.calls == 0


def test_a_menos_de_cinco_minutos_renueva_y_guarda_el_par(tmp_path):
    secrets = store(whoop_token_expiry=(NOW + timedelta(minutes=4)).isoformat())
    fake = FakeWhoop()
    assert call(tmp_path, secrets, fake) == "acc-1"
    assert fake.calls == 1
    assert (secrets["whoop_access_token"], secrets["whoop_refresh_token"]) == ("acc-1", "ref-1")
    assert datetime.fromisoformat(secrets["whoop_token_expiry"]) > datetime.now(UTC)


def test_con_seis_minutos_de_margen_no_renueva(tmp_path):
    secrets = store(whoop_token_expiry=(NOW + timedelta(minutes=6)).isoformat())
    fake = FakeWhoop()
    assert call(tmp_path, secrets, fake) == "acc-0" and fake.calls == 0


def test_el_par_se_guarda_antes_de_devolver_el_token_y_el_refresh_primero(tmp_path):
    secrets = store(whoop_token_expiry=NOW.isoformat())
    orden: list[str] = []

    def put(name: str, value: str) -> None:
        orden.append(name)
        secrets[name] = value

    token = whoop_tokens.get_access_token(
        tmp_path,
        http=FakeWhoop().client(),
        secret_getter=secrets.get,
        secret_setter=put,
        now=clock,
    )
    assert token == "acc-1"
    assert orden == ["whoop_refresh_token", "whoop_access_token", "whoop_token_expiry"]


def test_si_no_se_puede_guardar_el_par_no_se_entrega_el_token(tmp_path):
    secrets = store(whoop_token_expiry=NOW.isoformat())

    def put(name: str, value: str) -> None:
        raise OSError("llavero bloqueado")

    with pytest.raises(OSError):
        whoop_tokens.get_access_token(
            tmp_path,
            http=FakeWhoop().client(),
            secret_getter=secrets.get,
            secret_setter=put,
            now=clock,
        )


def test_sin_credenciales_pide_whoop_auth(tmp_path):
    secrets = store()
    del secrets["whoop_client_secret"]
    with pytest.raises(whoop_tokens.TokenError, match="whoop-auth"):
        call(tmp_path, secrets, FakeWhoop())
    secrets = store()
    del secrets["whoop_refresh_token"]
    with pytest.raises(whoop_tokens.TokenError, match="whoop-auth"):
        call(tmp_path, secrets, FakeWhoop())


def test_refresh_token_gastado_pide_whoop_auth(tmp_path):
    secrets = store(whoop_token_expiry=NOW.isoformat())
    with pytest.raises(whoop_tokens.TokenError, match="invalid_grant.*whoop-auth"):
        call(tmp_path, secrets, FakeWhoop(valid="otro"))
    assert secrets["whoop_refresh_token"] == "ref-0"  # nada a medias


def test_un_token_rechazado_se_renueva_aunque_no_haya_caducado(tmp_path):
    secrets = store()
    fake = FakeWhoop()
    assert call(tmp_path, secrets, fake, reject="acc-0") == "acc-1"
    assert fake.calls == 1


def test_si_otro_ya_renovo_el_token_rechazado_no_se_vuelve_a_renovar(tmp_path):
    secrets = store(whoop_access_token="acc-7")  # otro proceso ya lo sustituyó
    fake = FakeWhoop()
    assert call(tmp_path, secrets, fake, reject="acc-6") == "acc-7"
    assert fake.calls == 0


def api_answering(*statuses: int) -> tuple[list[str], object]:
    tokens_used: list[str] = []
    pending = list(statuses)

    def send(token: str) -> httpx.Response:
        tokens_used.append(token)
        return httpx.Response(pending.pop(0), json={})

    return tokens_used, send


def test_ante_401_renueva_una_vez_y_reintenta(tmp_path):
    secrets = store()
    fake = FakeWhoop()
    used, send = api_answering(401, 200)
    resp = whoop_tokens.call_with_token(
        send,  # type: ignore[arg-type]
        tmp_path,
        http=fake.client(),
        secret_getter=secrets.get,
        secret_setter=secrets.__setitem__,
        now=clock,
    )
    assert resp.status_code == 200
    assert used == ["acc-0", "acc-1"] and fake.calls == 1


def test_un_segundo_401_no_se_reintenta(tmp_path):
    secrets = store()
    fake = FakeWhoop()
    used, send = api_answering(401, 401)
    with pytest.raises(whoop_tokens.TokenError, match="401"):
        whoop_tokens.call_with_token(
            send,  # type: ignore[arg-type]
            tmp_path,
            http=fake.client(),
            secret_getter=secrets.get,
            secret_setter=secrets.__setitem__,
            now=clock,
        )
    assert len(used) == 2 and fake.calls == 1


def test_otros_errores_no_tocan_el_token(tmp_path):
    fake = FakeWhoop()
    used, send = api_answering(500)
    secrets = store()
    resp = whoop_tokens.call_with_token(
        send,  # type: ignore[arg-type]
        tmp_path,
        http=fake.client(),
        secret_getter=secrets.get,
        secret_setter=secrets.__setitem__,
        now=clock,
    )
    assert resp.status_code == 500 and fake.calls == 0


def test_dos_hilos_que_renuevan_a_la_vez_se_serializan(tmp_path):
    secrets = store(whoop_token_expiry=NOW.isoformat())
    lock = threading.Lock()

    def get(name: str) -> str | None:
        with lock:
            return secrets.get(name)

    def put(name: str, value: str) -> None:
        with lock:
            secrets[name] = value

    fake = FakeWhoop(delay_s=0.3)  # renovación lenta: sin bloqueo, el segundo la pisaría
    out: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            out.append(
                whoop_tokens.get_access_token(
                    tmp_path, http=fake.client(), secret_getter=get, secret_setter=put, now=clock
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert errors == []
    assert out == ["acc-1", "acc-1"]
    assert fake.calls == 1
    assert secrets["whoop_refresh_token"] == "ref-1" and secrets["whoop_access_token"] == "acc-1"


WORKER = """
import json, sys, time
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import parse_qsl
import httpx
from ares.connectors import whoop_tokens

d = Path(sys.argv[1])
store, server = d / "store.json", d / "server.json"

def get(name):
    return json.loads(store.read_text()).get(name)

def put(name, value):
    s = json.loads(store.read_text()); s[name] = value; store.write_text(json.dumps(s))

def handler(request):
    form = dict(parse_qsl(request.content.decode()))
    st = json.loads(server.read_text())
    st["calls"] += 1
    if form["refresh_token"] != st["valid"]:
        server.write_text(json.dumps(st))
        return httpx.Response(400, json={"error": "invalid_grant"})
    st["n"] += 1
    st["valid"] = "ref-%d" % st["n"]
    server.write_text(json.dumps(st))
    time.sleep(0.5)
    return httpx.Response(200, json={"access_token": "acc-%d" % st["n"],
                                     "refresh_token": st["valid"], "expires_in": 3600})

(d / ("ready-" + sys.argv[2])).touch()
while not (d / "go").exists():
    time.sleep(0.01)
print(whoop_tokens.get_access_token(
    d, http=httpx.Client(transport=httpx.MockTransport(handler)),
    secret_getter=get, secret_setter=put,
    now=lambda: datetime(2026, 10, 2, 7, 0, tzinfo=UTC)))
"""


def test_dos_procesos_que_renuevan_a_la_vez_se_serializan(tmp_path):
    """Como `ares serve` y un comando del CLI: almacén y servidor compartidos en ficheros
    (solo se tocan dentro del bloqueo), y salida a la vez."""
    (tmp_path / "store.json").write_text(json.dumps(store(whoop_token_expiry=NOW.isoformat())))
    (tmp_path / "server.json").write_text(json.dumps({"valid": "ref-0", "n": 0, "calls": 0}))
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, str(tmp_path), str(i)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(2)
    ]
    deadline = time.monotonic() + 20
    while not all((tmp_path / f"ready-{i}").exists() for i in range(2)):
        assert time.monotonic() < deadline, "los procesos no arrancaron"
        time.sleep(0.02)
    (tmp_path / "go").touch()
    results = [p.communicate(timeout=30) for p in procs]
    for p, (_, err) in zip(procs, results, strict=True):
        assert p.returncode == 0, err
    assert [out.strip() for out, _ in results] == ["acc-1", "acc-1"]
    server = json.loads((tmp_path / "server.json").read_text())
    assert server["calls"] == 1
    final = json.loads((tmp_path / "store.json").read_text())
    assert (final["whoop_access_token"], final["whoop_refresh_token"]) == ("acc-1", "ref-1")
