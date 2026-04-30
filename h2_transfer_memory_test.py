#!/usr/bin/env python3
from __future__ import annotations

import argparse
import socket
import struct

from hpack import Decoder

from common import h2
from common.backend import start_stream_echo_backend
from common.memory import run_memory_rounds
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


def _drain_until_headers(sock: socket.socket, stream_id: int, padding: bool) -> None:
    decoder = Decoder()
    while True:
        item = h2.read_frame(sock)
        if item is None:
            raise RuntimeError("connection closed before CONNECT response")
        frame_type, flags, sid, data = item
        if frame_type == 0x4 and not (flags & 0x1):
            sock.sendall(h2.frame(0x4, 0x1, 0))
            continue
        if sid == stream_id and frame_type == 0x1:
            headers = h2.decode_headers(decoder, data)
            if int(headers.get(":status", "0")) != 200:
                raise RuntimeError(f"CONNECT returned headers {headers}")
            if padding:
                h2.assert_padding_response(headers)
            return


def _recv_payload(sock: socket.socket, stream_id: int, padding: bool, want: int) -> bytes:
    chunks: list[bytes] = []
    got = 0
    padded = bytearray()
    while got < want:
        item = h2.read_frame(sock)
        if item is None:
            raise RuntimeError("connection closed while reading tunnel data")
        frame_type, flags, sid, data = item
        if frame_type == 0x4 and not (flags & 0x1):
            sock.sendall(h2.frame(0x4, 0x1, 0))
            continue
        if sid != stream_id or frame_type != 0x0 or not data:
            continue
        if padding:
            padded.extend(data)
            while h2.padded_frame_complete(padded):
                payload_size = int.from_bytes(padded[:2], "big")
                padding_size = padded[2]
                frame_size = 3 + payload_size + padding_size
                payload = h2.unpad_data(bytes(padded[:frame_size]))
                del padded[:frame_size]
                chunks.append(payload)
                got += len(payload)
        else:
            chunks.append(data)
            got += len(data)
        if data:
            increment = len(data)
            sock.sendall(h2.frame(0x8, 0x0, 0, struct.pack("!I", increment)))
            sock.sendall(h2.frame(0x8, 0x0, stream_id, struct.pack("!I", increment)))
    return b"".join(chunks)


def transfer_once(host: str, port: int, authority: str, size: int, padding: bool) -> None:
    chunk_size = 8192
    payload = b"x" * chunk_size
    stream_id = 1
    sent = 0
    received = 0

    with h2.connect_tls(host, port) as sock:
        sock.settimeout(10)
        sock.sendall(h2.frame(0x1, 0x4, stream_id, h2.connect_headers(authority, padding=padding)))
        _drain_until_headers(sock, stream_id, padding)

        while received < size:
            n = min(chunk_size, size - sent)
            data = payload[:n]
            if padding:
                data = h2.padded_data(data, padding_size=7)
            sock.sendall(h2.frame(0x0, 0x0, stream_id, data))
            sent += n

            echoed = _recv_payload(sock, stream_id, padding, n)
            if echoed != payload[:n]:
                raise RuntimeError("echo payload mismatch")
            received += n

        sock.sendall(h2.frame(0x3, 0x0, stream_id, struct.pack("!I", 0)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/2 CONNECT transfer memory test.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--listen-port", type=int, default=3328)
    parser.add_argument("--backend-port", type=int, default=20080)
    parser.add_argument("--padding", action="store_true")
    args = parser.parse_args()

    start_stream_echo_backend(args.backend_port)
    config = NginxConfig(args.listen_port, args.backend_port, padding=args.padding, root_response=False)
    with NginxTestServer(args.nginx, config) as server:
        return run_memory_rounds(
            pid=server.pid,
            rounds=args.rounds,
            requests=1,
            runner=lambda _: transfer_once(
                "127.0.0.1",
                args.listen_port,
                f"127.0.0.1:{args.backend_port}",
                args.bytes,
                args.padding,
            ),
        )


if __name__ == "__main__":
    raise SystemExit(main())
