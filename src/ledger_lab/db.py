"""Postgres readiness check."""

import logging
from dataclasses import dataclass

import psycopg

_log = logging.getLogger(__name__)

# SELECT 1 returns one column whose value is 1 when the server is answering.
_READY_ROW = (1,)


@dataclass(frozen=True, slots=True)
class DatabaseCheck:
    ready: bool
    reason: str


def check_database(database_url: str, timeout_seconds: int) -> DatabaseCheck:
    """Return whether Postgres answers SELECT 1.

    Reasons are stable codes. Driver exception text is not returned or logged,
    because it can contain the connection string.
    """
    try:
        with psycopg.connect(database_url, connect_timeout=timeout_seconds) as connection:
            row = connection.execute("SELECT 1").fetchone()
    except psycopg.OperationalError:
        _log.warning("database unreachable")
        return DatabaseCheck(ready=False, reason="unreachable")
    except psycopg.Error:
        _log.warning("database check failed")
        return DatabaseCheck(ready=False, reason="unavailable")

    if row != _READY_ROW:
        _log.warning("database check returned an unexpected result")
        return DatabaseCheck(ready=False, reason="unexpected_result")
    return DatabaseCheck(ready=True, reason="ok")
