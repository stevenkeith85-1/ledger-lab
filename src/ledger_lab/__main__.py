"""Node process entrypoint."""

import logging
import os
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
    A worker that raises logs the error and sends SIGTERM. The signal stays
    blocked, so ``sigwait`` consumes it and the process exits 1.
    """
    signal.pthread_sigmask(signal.SIG_BLOCK, _STOP_SIGNALS)
    failed = threading.Event()

    def serve() -> None:
        try:
            server.serve_forever()
        except BaseException:
            _log.exception("http server stopped")
            failed.set()
            # Every thread inherits the blocked mask, so this stays pending
            # until sigwait. The default terminate action does not run.
            os.kill(os.getpid(), signal.SIGTERM)

    worker = threading.Thread(target=serve, name="ledger-lab-http")
    try:
        worker.start()
        signum = signal.sigwait(_STOP_SIGNALS)
        _log.info("shutting down signal=%s", signum)
        # shutdown() waits on an event serve_forever sets when it returns.
        # Skip it when the worker has already exited, or that wait hangs.
        if worker.is_alive():
            server.shutdown()
        server.server_close()
        worker.join()
        if failed.is_set():
            raise SystemExit(1)
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, _STOP_SIGNALS)


if __name__ == "__main__":
    main()
