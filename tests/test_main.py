"""Process startup failure paths."""

import logging

import pytest

from ledger_lab.__main__ import main

_PASSWORD = "placeholder"
_CONFIG_ENV = ("PORT", "LOG_LEVEL", "DB_CONNECT_TIMEOUT_SECONDS")


def _clear_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in _CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)


def test_main_exits_when_database_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_config(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        main()
    captured = capsys.readouterr()
    assert caught.value.code == 1
    assert "DATABASE_URL is required" in captured.out


def test_main_logs_configuration_errors_without_the_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_config(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"mysql://ledger:{_PASSWORD}@db/ledger")
    with pytest.raises(SystemExit) as caught:
        main()
    captured = capsys.readouterr()
    assert caught.value.code == 1
    assert _PASSWORD not in captured.out
    assert _PASSWORD not in captured.err
    assert logging.getLogger("psycopg").level == logging.WARNING
