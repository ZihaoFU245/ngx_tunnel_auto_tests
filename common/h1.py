from __future__ import annotations

import socket
import ssl

from .paths import AUTH


def _tls_socket(host: str, port: int) -> ssl.SSLSocket:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((host, port), timeout=5)
    sock = ctx.wrap_socket(raw, server_hostname=host)
    sock.settimeout(5)
    return sock


def request(host: str, port: int, payload: bytes) -> bytes:
    with _tls_socket(host, port) as sock:
        sock.sendall(payload)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data


def get(host: str, port: int) -> int:
    response = request(host, port, b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    return int(response.split(b" ", 2)[1])


def connect(host: str, port: int, authority: str) -> int:
    response = request(
        host,
        port,
        (
            f"CONNECT {authority} HTTP/1.1\r\n"
            f"Host: {authority}\r\n"
            f"Proxy-Authorization: {AUTH}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii"),
    )
    return int(response.split(b" ", 2)[1])

