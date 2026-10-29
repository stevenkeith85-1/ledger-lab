"""The node exits 0 on SIGTERM and SIGINT and closes its socket."""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

# Bound for the process to accept /health. Each attempt returns as soon as
# the connection is refused, or after the per-request timeout below.
_START_TIMEOUT_SECONDS = 5
_HEALTH_REQUEST_TIMEOUT_SECONDS = 0.2
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
