from __future__ import annotations

import asyncio
import socket
import ssl
import struct
import time

from .paths import AUTH


def _hpack_int(value: int, prefix_bits: int, first: int) -> bytes:
    max_prefix = (1 << prefix_bits) - 1
    if value < max_prefix:
        return bytes([first | value])
    out = bytearray([first | max_prefix])
    value -= max_prefix
    while value >= 128:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _hpack_string(value: str) -> bytes:
    data = value.encode("ascii")
    return _hpack_int(len(data), 7, 0) + data


def _literal_indexed_name(index: int, value: str) -> bytes:
    return _hpack_int(index, 4, 0) + _hpack_string(value)


def _literal_new_name(name: str, value: str) -> bytes:
    return b"\x00" + _hpack_string(name) + _hpack_string(value)


def frame(frame_type: int, flags: int, stream_id: int, payload: bytes = b"") -> bytes:
    return (
        len(payload).to_bytes(3, "big")
        + bytes([frame_type, flags])
        + struct.pack("!I", stream_id & 0x7FFFFFFF)
        + payload
    )


def _read_exact(sock: ssl.SSLSocket, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def read_frame(sock: ssl.SSLSocket):
    header = _read_exact(sock, 9)
    if header is None:
        return None
    length = int.from_bytes(header[:3], "big")
    payload = _read_exact(sock, length)
    if payload is None:
        return None
    return header[3], header[4], struct.unpack("!I", header[5:9])[0], payload


async def read_async_frame(reader: asyncio.StreamReader):
    header = await reader.readexactly(9)
    length = int.from_bytes(header[:3], "big")
    payload = await reader.readexactly(length)
    return header[3], header[4], struct.unpack("!I", header[5:9])[0], payload


def connect_tls(host: str, port: int) -> ssl.SSLSocket:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2"])
    raw = socket.create_connection((host, port), timeout=5)
    sock = ctx.wrap_socket(raw, server_hostname=host)
    sock.settimeout(5)
    if sock.selected_alpn_protocol() != "h2":
        raise RuntimeError("h2 was not negotiated")
    sock.sendall(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
    sock.sendall(frame(0x4, 0x0, 0, b""))
    return sock


async def connect_async(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2"])
    reader, writer = await asyncio.open_connection(host, port, ssl=ctx, server_hostname=host)
    ssl_object = writer.get_extra_info("ssl_object")
    if ssl_object.selected_alpn_protocol() != "h2":
        raise RuntimeError("h2 was not negotiated")
    writer.write(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
    writer.write(frame(0x4, 0x0, 0, b""))
    await writer.drain()
    return reader, writer


def request_get(sock: ssl.SSLSocket, stream_id: int, authority: str) -> None:
    block = b"".join([b"\x82", b"\x84", b"\x87", _literal_indexed_name(1, authority)])
    sock.sendall(frame(0x1, 0x5, stream_id, block))
    _wait_stream_done(sock, stream_id)


def request_connect(
    sock: ssl.SSLSocket,
    stream_id: int,
    authority: str,
    *,
    reset_after_headers: bool = True,
) -> None:
    block = b"".join(
        [
            _literal_indexed_name(2, "CONNECT"),
            _literal_indexed_name(1, authority),
            _literal_new_name("proxy-authorization", AUTH),
        ]
    )
    sock.sendall(frame(0x1, 0x5, stream_id, block))
    _wait_stream_done(sock, stream_id, reset_after_headers=reset_after_headers)


def connect_headers(authority: str) -> bytes:
    return b"".join(
        [
            _literal_indexed_name(2, "CONNECT"),
            _literal_indexed_name(1, authority),
            _literal_new_name("proxy-authorization", AUTH),
        ]
    )


def _wait_stream_done(sock: ssl.SSLSocket, stream_id: int, *, reset_after_headers: bool = False) -> None:
    got_headers = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        item = read_frame(sock)
        if item is None:
            raise RuntimeError("connection closed while waiting for h2 response")
        frame_type, flags, sid, _ = item
        if frame_type == 0x4 and not (flags & 0x1):
            sock.sendall(frame(0x4, 0x1, 0))
            continue
        if sid != stream_id:
            continue
        if frame_type == 0x1:
            got_headers = True
        if reset_after_headers and got_headers:
            sock.sendall(frame(0x3, 0x0, stream_id, struct.pack("!I", 0)))
            return
        if flags & 0x1:
            return
    raise TimeoutError(f"h2 stream {stream_id} did not finish")


async def run_connects(host: str, port: int, authority: str, total: int, concurrency: int) -> None:
    reader, writer = await connect_async(host, port)
    pending: dict[int, asyncio.Future[None]] = {}
    sent = 0
    completed = 0
    next_stream_id = 1
    block = connect_headers(authority)

    async def fill_window() -> None:
        nonlocal sent, next_stream_id
        while sent < total and len(pending) < concurrency:
            stream_id = next_stream_id
            next_stream_id += 2
            sent += 1
            pending[stream_id] = asyncio.get_running_loop().create_future()
            writer.write(frame(0x1, 0x5, stream_id, block))
        await writer.drain()

    await fill_window()
    while completed < total:
        frame_type, flags, stream_id, _ = await read_async_frame(reader)
        if frame_type == 0x4 and not (flags & 0x1):
            writer.write(frame(0x4, 0x1, 0))
            await writer.drain()
            continue
        future = pending.get(stream_id)
        if frame_type == 0x1 and future is not None and not future.done():
            writer.write(frame(0x3, 0x0, stream_id, struct.pack("!I", 0)))
            future.set_result(None)
            completed += 1
            del pending[stream_id]
            await fill_window()
    writer.close()
    await writer.wait_closed()
