"""scripts/tcp_forward.py relays bytes both ways to its one fixed target."""

import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tcp_forward.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_relays_both_ways() -> None:
    target = socket.create_server(("127.0.0.1", 0))
    listen = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            str(listen),
            "127.0.0.1",
            str(target.getsockname()[1]),
        ]
    )
    try:
        for _ in range(50):
            try:
                client = socket.create_connection(("127.0.0.1", listen), 1)
                break
            except OSError:
                time.sleep(0.1)
        with client, target:
            conn, _ = target.accept()
            with conn:
                client.sendall(b"ping")
                assert conn.recv(4) == b"ping"
                conn.sendall(b"pong")
                assert client.recv(4) == b"pong"
    finally:
        proc.terminate()
        proc.wait(5)
