"""Node process entrypoint."""

import logging
import signal
import sys
from http.server import ThreadingHTTPServer
from types import FrameType

from ledger_lab.config import Settings, SettingsError
from ledger_lab.server import make_server

_log = logging.getLogger("ledger_lab")


def main() -> None:
    try:
        settings = Settings.from_environ()
    except SettingsError as exc:
        _configure_logging("ERROR")
        _log.error("%s", exc)
        raise SystemExit(1) from None

    _configure_logging(settings.log_level)
    server = make_server(settings)
    _stop_on_signal(server)
    _log.info("listening port=%s", settings.port)
    server.serve_forever()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
    # The driver logs failed connection attempts at DEBUG, including details
    # from the connection string. Keep those off stdout.
    logging.getLogger("psycopg").setLevel(logging.WARNING)


def _stop_on_signal(server: ThreadingHTTPServer) -> None:
    def stop(signum: int, _frame: FrameType | None) -> None:
        _log.info("shutting down signal=%s", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


if __name__ == "__main__":
    main()
