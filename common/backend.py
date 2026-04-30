from __future__ import annotations

import socket
import struct
import sys
import threading
import time
import select
from pathlib import Path

from .process import ProcessSet


def wait_tcp_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        if result == 0:
            return
        time.sleep(0.05)
    raise RuntimeError(f"TCP port {port} did not open")


def start_http_backend(processes: ProcessSet, workdir: Path, port: int):
    proc = processes.start(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=workdir,
    )
    wait_tcp_port(port)
    return proc


def start_echo_backend(port: int) -> threading.Thread:
    thread = threading.Thread(target=echo_backend, args=(port,), daemon=True)
    thread.start()
    wait_tcp_port(port)
    return thread


def echo_backend(port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(512)
    while True:
        readable, _, _ = select.select([listener], [], [], 0.2)
        if readable:
            conn, _ = listener.accept()
            threading.Thread(target=echo_connection, args=(conn,), daemon=True).start()


def echo_connection(conn: socket.socket) -> None:
    data = conn.recv(65535)
    if data:
        conn.sendall(data)
    conn.close()


def reset_backend(port: int, stop: threading.Event) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    while not stop.is_set():
        readable, _, _ = select.select([listener], [], [], 0.2)
        if readable:
            conn, _ = listener.accept()
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            conn.close()
    listener.close()
