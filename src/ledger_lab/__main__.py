"""Node process entrypoint."""

import logging
import signal
import sys
import threading
from http.server import ThreadingHTTPServer

from ledger_lab.config import Settings, SettingsError
from ledger_lab.server import make_server

_log = logging.getLogger("ledger_lab")

# Consumed by sigwait on the main thread. They stay blocked so the default
# terminate action cannot run, and so a handler cannot call shutdown().
_STOP_SIGNALS = {signal.SIGTERM, signal.SIGINT}


def main() -> None:
    try:
        settings = Settings.from_environ()
    except SettingsError as exc:
        _configure_logging("ERROR")
        _log.error("%s", exc)
        raise SystemExit(1) from None

    _configure_logging(settings.log_level)
    server = make_server(settings)
    _log.info("listening port=%s", settings.port)
    _serve_until_signal(server)


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


def _serve_until_signal(server: ThreadingHTTPServer) -> None:
    """Accept until SIGTERM or SIGINT, then close the listening socket.

    ``shutdown()`` waits until ``serve_forever()`` returns. That loop runs on
    a worker thread so this thread can call ``shutdown()`` without deadlocking.
    """
    signal.pthread_sigmask(signal.SIG_BLOCK, _STOP_SIGNALS)
    worker = threading.Thread(target=server.serve_forever, name="ledger-lab-http")
    worker.start()
    signum = signal.sigwait(_STOP_SIGNALS)
    _log.info("shutting down signal=%s", signum)
    server.shutdown()
    server.server_close()
    worker.join()


if __name__ == "__main__":
    main()
