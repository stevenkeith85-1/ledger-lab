"""The node exits 0 on SIGTERM and SIGINT and closes its socket."""

import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ledger_lab.__main__ import _serve_until_signal

# Bound for the process to accept /health. Each attempt returns as soon as
# the connection is refused, or after the per-request timeout below.
_START_TIMEOUT_SECONDS = 5
_HEALTH_REQUEST_TIMEOUT_SECONDS = 0.2
# Pause after a refused connection so the readiness poll does not spin.
_POLL_INTERVAL_SECONDS = 0.05
# The process must exit inside this bound after the stop signal.
_STOP_TIMEOUT_SECONDS = 2


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert isinstance(port, int)
    return port


def _start_node(port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PORT"] = str(port)
    env["DATABASE_URL"] = "postgresql://ledger:ledger@127.0.0.1:1/ledger"
    env["LOG_LEVEL"] = "INFO"
    env["DB_CONNECT_TIMEOUT_SECONDS"] = "1"
    return subprocess.Popen(
        [sys.executable, "-m", "ledger_lab"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _output(proc: subprocess.Popen[bytes]) -> str:
    stdout, stderr = proc.communicate()
    return f"stdout={stdout!r}\nstderr={stderr!r}"


def _wait_until_healthy(port: int, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"node exited before /health\n{_output(proc)}")
        try:
            with urllib.request.urlopen(url, timeout=_HEALTH_REQUEST_TIMEOUT_SECONDS) as response:
                if response.status == 200:
                    return
        except urllib.error.URLError, TimeoutError, OSError:
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
    proc.kill()
    raise AssertionError(f"timed out waiting for /health\n{_output(proc)}")


def _assert_port_closed(port: int) -> None:
    try:
        connected = socket.create_connection(
            ("127.0.0.1", port),
            timeout=_HEALTH_REQUEST_TIMEOUT_SECONDS,
        )
    except ConnectionRefusedError:
        return
    connected.close()
    raise AssertionError(f"port {port} still accepts connections")


@pytest.mark.parametrize(
    "stop_signal",
    [signal.SIGTERM, signal.SIGINT],
    ids=["SIGTERM", "SIGINT"],
)
def test_signal_stops_the_node(stop_signal: signal.Signals) -> None:
    port = _free_port()
    proc = _start_node(port)
    try:
        _wait_until_healthy(port, proc)
        proc.send_signal(stop_signal)
        try:
            code = proc.wait(timeout=_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AssertionError(
                f"{stop_signal.name} did not stop the node\n{_output(proc)}"
            ) from None
        assert code == 0
        _assert_port_closed(port)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=_STOP_TIMEOUT_SECONDS)


class _ExplodingServer(ThreadingHTTPServer):
    def _handle_request_noblock(self) -> None:
        raise RuntimeError("serve failed")


def test_server_failure_exits_1(caplog: pytest.LogCaptureFixture) -> None:
    server = _ExplodingServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    assert isinstance(port, int)
    # Queue one connection so the worker's first poll returns immediately.
    client = socket.create_connection(("127.0.0.1", port))
    try:
        caplog.set_level(logging.ERROR, logger="ledger_lab")
        with pytest.raises(SystemExit) as caught:
            _serve_until_signal(server)
        assert caught.value.code == 1
        assert "serve failed" in caplog.text
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", port), timeout=_HEALTH_REQUEST_TIMEOUT_SECONDS)
    finally:
        client.close()
        server.server_close()
