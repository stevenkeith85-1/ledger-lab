"""Database readiness, including an unreachable server."""

import logging
from collections.abc import Callable

import psycopg
import pytest

from ledger_lab.db import DatabaseCheck, check_database

_PASSWORD = "placeholder"
_URL = f"postgresql://ledger:{_PASSWORD}@db.example/ledger"
_TIMEOUT_SECONDS = 3


class _Connection:
    def __init__(self, row: tuple[int, ...] | None, queries: list[str]) -> None:
        self._row = row
        self._queries = queries

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, query: str) -> _Connection:
        self._queries.append(query)
        return self

    def fetchone(self) -> tuple[int, ...] | None:
        return self._row


def _connect(row: tuple[int, ...] | None, queries: list[str]) -> Callable[..., _Connection]:
    def connect(_dsn: str, *, connect_timeout: int) -> _Connection:
        assert connect_timeout == _TIMEOUT_SECONDS
        return _Connection(row, queries)

    return connect


def test_ready_when_select_one_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    queries: list[str] = []
    monkeypatch.setattr("ledger_lab.db.psycopg.connect", _connect((1,), queries))
    assert check_database(_URL, _TIMEOUT_SECONDS) == DatabaseCheck(ready=True, reason="ok")
    assert queries == ["SELECT 1"]


def test_not_ready_when_result_is_unexpected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ledger_lab.db.psycopg.connect", _connect((2,), []))
    result = check_database(_URL, _TIMEOUT_SECONDS)
    assert result == DatabaseCheck(ready=False, reason="unexpected_result")


def test_operational_error_is_unreachable_and_unlogged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def connect(*_args: object, **_kwargs: object) -> _Connection:
        raise psycopg.OperationalError(f"password={_PASSWORD}")

    monkeypatch.setattr("ledger_lab.db.psycopg.connect", connect)
    with caplog.at_level(logging.DEBUG):
        result = check_database(_URL, _TIMEOUT_SECONDS)
    assert result == DatabaseCheck(ready=False, reason="unreachable")
    assert _PASSWORD not in caplog.text


def test_other_driver_error_is_unavailable_and_unlogged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def connect(*_args: object, **_kwargs: object) -> _Connection:
        raise psycopg.Error(f"password={_PASSWORD}")

    monkeypatch.setattr("ledger_lab.db.psycopg.connect", connect)
    with caplog.at_level(logging.DEBUG):
        result = check_database(_URL, _TIMEOUT_SECONDS)
    assert result == DatabaseCheck(ready=False, reason="unavailable")
    assert _PASSWORD not in caplog.text


def test_refused_connection_is_unreachable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    url = f"postgresql://ledger:{_PASSWORD}@127.0.0.1:1/ledger"
    with caplog.at_level(logging.DEBUG):
        result = check_database(url, timeout_seconds=2)
    assert result == DatabaseCheck(ready=False, reason="unreachable")
    assert _PASSWORD not in caplog.text
