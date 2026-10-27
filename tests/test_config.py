"""Settings failure paths and environment parsing."""

import pytest

from ledger_lab.config import Settings, SettingsError

_PASSWORD = "placeholder"


def test_from_environ_reads_values() -> None:
    settings = Settings.from_environ(
        {
            "PORT": "9090",
            "DATABASE_URL": f"postgresql://ledger:{_PASSWORD}@db:5432/ledger",
            "LOG_LEVEL": "debug",
            "DB_CONNECT_TIMEOUT_SECONDS": "4",
        }
    )
    assert settings.port == 9090
    assert settings.database_url == f"postgresql://ledger:{_PASSWORD}@db:5432/ledger"
    assert settings.log_level == "DEBUG"
    assert settings.db_connect_timeout_seconds == 4


def test_accepts_postgres_scheme_alias_and_defaults() -> None:
    settings = Settings.from_environ({"DATABASE_URL": "postgres://localhost/ledger"})
    assert settings.database_url == "postgres://localhost/ledger"
    assert settings.port == 8080
    assert settings.log_level == "INFO"
    assert settings.db_connect_timeout_seconds == 3


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "DATABASE_URL is required"),
        ({"DATABASE_URL": "  "}, "DATABASE_URL is empty"),
        (
            {"DATABASE_URL": f"mysql://ledger:{_PASSWORD}@db/ledger"},
            "DATABASE_URL must use the postgresql scheme",
        ),
        ({"DATABASE_URL": "postgresql:///ledger"}, "DATABASE_URL must include a host"),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "PORT": "nope"},
            "PORT must be an integer",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "PORT": "0"},
            "PORT must be between 1 and 65535",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "PORT": "65536"},
            "PORT must be between 1 and 65535",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "PORT": ""},
            "PORT is empty",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "LOG_LEVEL": "verbose"},
            "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "DB_CONNECT_TIMEOUT_SECONDS": "0"},
            "DB_CONNECT_TIMEOUT_SECONDS must be at least 1",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "DB_CONNECT_TIMEOUT_SECONDS": "1.5"},
            "DB_CONNECT_TIMEOUT_SECONDS must be an integer",
        ),
        (
            {"DATABASE_URL": "postgresql://localhost/ledger", "DB_CONNECT_TIMEOUT_SECONDS": "-1"},
            "DB_CONNECT_TIMEOUT_SECONDS must be an integer",
        ),
    ],
)
def test_rejects_invalid_environ(env: dict[str, str], message: str) -> None:
    with pytest.raises(SettingsError, match=message) as caught:
        Settings.from_environ(env)
    assert _PASSWORD not in str(caught.value)
