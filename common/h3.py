from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated

from .paths import AUTH


@dataclass
class StreamState:
    response_ready: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    status: int | None = None


class H3Client(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.h3: H3Connection | None = None
        self.ready = asyncio.Event()
        self.streams: dict[int, StreamState] = {}

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated) and event.alpn_protocol in H3_ALPN:
            self.h3 = H3Connection(self._quic)
            self.ready.set()
            return
        if self.h3 is None:
            return
        for ev in self.h3.handle_event(event):
            if isinstance(ev, HeadersReceived):
                state = self.streams.setdefault(ev.stream_id, StreamState())
                for name, value in ev.headers:
                    if name == b":status":
                        state.status = int(value)
                state.response_ready.set()
                if ev.stream_ended:
                    state.done.set()
            elif isinstance(ev, DataReceived):
                state = self.streams.setdefault(ev.stream_id, StreamState())
                if ev.stream_ended:
                    state.done.set()

    async def request(self, headers: list[tuple[bytes, bytes]], *, end_stream: bool) -> int:
        if self.h3 is None:
            await self.ready.wait()
        assert self.h3 is not None
        stream_id = self._quic.get_next_available_stream_id()
        state = StreamState()
        self.streams[stream_id] = state
        self.h3.send_headers(stream_id=stream_id, headers=headers, end_stream=end_stream)
        self.transmit()
        await asyncio.wait_for(state.response_ready.wait(), timeout=5)
        return state.status or 0


async def _with_client(host: str, port: int, fn):
    conf = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    conf.verify_mode = ssl.CERT_NONE
    async with connect(host, port, configuration=conf, create_protocol=H3Client, wait_connected=True) as client:
        return await fn(client)


async def get(host: str, port: int) -> int:
    async def run(client: H3Client) -> int:
        return await client.request(
            [(b":method", b"GET"), (b":scheme", b"https"), (b":authority", b"localhost"), (b":path", b"/")],
            end_stream=True,
        )

    return await _with_client(host, port, run)


async def connect_once(host: str, port: int, authority: str) -> int:
    async def run(client: H3Client) -> int:
        return await client.request(
            [
                (b":method", b"CONNECT"),
                (b":authority", authority.encode("ascii")),
                (b"proxy-authorization", AUTH.encode("ascii")),
            ],
            end_stream=True,
        )

    return await _with_client(host, port, run)


async def run_connects(host: str, port: int, authority: str, total: int, concurrency: int) -> None:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(client: H3Client) -> None:
        async with semaphore:
            status = await client.request(
                [
                    (b":method", b"CONNECT"),
                    (b":authority", authority.encode("ascii")),
                    (b"proxy-authorization", AUTH.encode("ascii")),
                ],
                end_stream=True,
            )
            if status < 200 or status >= 300:
                raise RuntimeError(f"h3 CONNECT returned {status}")

    async def run(client: H3Client) -> None:
        await asyncio.gather(*(one(client) for _ in range(total)))

    await _with_client(host, port, run)
