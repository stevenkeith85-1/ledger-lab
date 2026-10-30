"""HTTP liveness and readiness."""

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ledger_lab.config import Settings
from ledger_lab.db import check_database

_log = logging.getLogger(__name__)

# Published ports and the Compose healthcheck connect from outside the loopback interface.
BIND_HOST = "0.0.0.0"


def make_server(
    settings: Settings,
    *,
    host: str = BIND_HOST,
    port: int | None = None,
) -> ThreadingHTTPServer:
    listen_port = settings.port if port is None else port
    return ThreadingHTTPServer((host, listen_port), _handler(settings))


def _handler(settings: Settings) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            _route(self, settings)

        # The parameter name matches BaseHTTPRequestHandler.log_message.
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            _log.info("http %s", format % args)

    return Handler


def _route(handler: BaseHTTPRequestHandler, settings: Settings) -> None:
    path = handler.path.split("?", 1)[0]
    if path == "/health":
        _write(handler, HTTPStatus.OK, {"status": "ok"})
        return
    if path == "/ready":
        result = check_database(settings.database_url, settings.db_connect_timeout_seconds)
        if result.ready:
            _write(handler, HTTPStatus.OK, {"status": "ready"})
            return
        _write(
            handler,
            HTTPStatus.SERVICE_UNAVAILABLE,
            {"status": "not_ready", "reason": result.reason},
        )
        return
    _write(handler, HTTPStatus.NOT_FOUND, {"status": "not_found"})


def _write(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: dict[str, str]) -> None:
    payload = json.dumps(body).encode("utf-8")
    try:
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
    except ConnectionError:
        # The readiness probe closes the socket when its own timeout fires
        # before this response is written.
        return
