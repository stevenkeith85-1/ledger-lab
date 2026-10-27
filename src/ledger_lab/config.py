"""Process configuration loaded from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

# Default listen port for GCP and local Compose. Override with PORT.
DEFAULT_PORT = 8080
DEFAULT_LOG_LEVEL = "INFO"
# Bounds a readiness probe so an unreachable database fails quickly.
DEFAULT_DB_CONNECT_TIMEOUT_SECONDS = 3

_MIN_PORT = 1
_MAX_PORT = 65535
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})


class SettingsError(Exception):
    """The process environment is not valid to start the node."""


@dataclass(frozen=True, slots=True)
class Settings:
    port: int
    database_url: str
    log_level: str
    db_connect_timeout_seconds: int

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        return cls(
            port=_port(env.get("PORT")),
            database_url=_database_url(env.get("DATABASE_URL")),
            log_level=_log_level(env.get("LOG_LEVEL")),
            db_connect_timeout_seconds=_timeout(env.get("DB_CONNECT_TIMEOUT_SECONDS")),
        )


def _present(name: str, value: str | None, default: str | None) -> str:
    if value is None:
        if default is None:
            raise SettingsError(f"{name} is required")
        return default
    stripped = value.strip()
    if stripped == "":
        raise SettingsError(f"{name} is empty")
    return stripped


def _port(value: str | None) -> int:
    raw = _present("PORT", value, str(DEFAULT_PORT))
    if not raw.isdecimal():
        raise SettingsError("PORT must be an integer")
    port = int(raw)
    if port < _MIN_PORT or port > _MAX_PORT:
        raise SettingsError(f"PORT must be between {_MIN_PORT} and {_MAX_PORT}")
    return port


def _database_url(value: str | None) -> str:
    raw = _present("DATABASE_URL", value, None)
    parts = urlsplit(raw)
    if parts.scheme not in _POSTGRES_SCHEMES:
        raise SettingsError("DATABASE_URL must use the postgresql scheme")
    if parts.hostname is None or parts.hostname == "":
        raise SettingsError("DATABASE_URL must include a host")
    return raw


def _log_level(value: str | None) -> str:
    raw = _present("LOG_LEVEL", value, DEFAULT_LOG_LEVEL).upper()
    if raw not in _LOG_LEVELS:
        raise SettingsError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    return raw


def _timeout(value: str | None) -> int:
    raw = _present(
        "DB_CONNECT_TIMEOUT_SECONDS",
        value,
        str(DEFAULT_DB_CONNECT_TIMEOUT_SECONDS),
    )
    if not raw.isdecimal():
        raise SettingsError("DB_CONNECT_TIMEOUT_SECONDS must be an integer")
    parsed = int(raw)
    if parsed < 1:
        raise SettingsError("DB_CONNECT_TIMEOUT_SECONDS must be at least 1")
    return parsed
