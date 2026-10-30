"""HTTP liveness and readiness."""

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from ledger_lab.config import Settings
from ledger_lab.db import DatabaseCheck
from ledger_lab.server import make_server

_PASSWORD = "placeholder"
_CLIENT_TIMEOUT_SECONDS = 2


@pytest.fixture
def port() -> Iterator[int]:
    settings = Settings(
        port=8080,
        database_url=f"postgresql://ledger:{_PASSWORD}@127.0.0.1:1/ledger",
        log_level="INFO",
        db_connect_timeout_seconds=1,
    )
    server = make_server(settings, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound = server.server_address[1]
    assert isinstance(bound, int)
    try:
        yield bound
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(port: int, path: str) -> tuple[int, dict[str, str]]:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}",
            timeout=_CLIENT_TIMEOUT_SECONDS,
        ) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    return status, _json_object(raw)


def _json_object(raw: bytes) -> dict[str, str]:
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise AssertionError(raw)
    body: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise AssertionError(raw)
        body[key] = value
    return body


def test_health_is_ok_when_database_is_down(port: int) -> None:
    status, body = _get(port, "/health")
    assert status == 200
    assert body == {"status": "ok"}


def test_health_ignores_query_string(port: int) -> None:
    status, body = _get(port, "/health?check=1")
    assert status == 200
    assert body == {"status": "ok"}


def test_ready_is_unavailable_when_database_refuses(port: int) -> None:
    status, body = _get(port, "/ready")
    assert status == 503
    assert body == {"status": "not_ready", "reason": "unreachable"}
    assert _PASSWORD not in json.dumps(body)


def test_ready_is_ok_when_database_check_passes(
    port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def ready(_database_url: str, _timeout_seconds: int) -> DatabaseCheck:
        return DatabaseCheck(ready=True, reason="ok")

    monkeypatch.setattr("ledger_lab.server.check_database", ready)
    status, body = _get(port, "/ready")
    assert status == 200
    assert body == {"status": "ready"}


def test_unknown_path_is_not_found(port: int) -> None:
    status, body = _get(port, "/missing")
    assert status == 404
    assert body == {"status": "not_found"}
