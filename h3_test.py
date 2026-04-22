import asyncio
import ssl

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated


PROXY_HOST = "mirror.zihaofu245.me"   # change this
PROXY_PORT = 443
TARGET = "example.com:443"


class Client(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.h3 = None
        self.http_ready = asyncio.Event()
        self.response_ready = asyncio.Event()
        self.ok = False

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated) and event.alpn_protocol in H3_ALPN:
            self.h3 = H3Connection(self._quic)
            self.http_ready.set()
            return

        if self.h3 is None:
            return

        for ev in self.h3.handle_event(event):
            if isinstance(ev, HeadersReceived):
                print("response headers:")
                for k, v in ev.headers:
                    print(k.decode(), v.decode())

                for k, v in ev.headers:
                    if k == b":status" and v.startswith(b"2"):
                        self.ok = True

                self.response_ready.set()

    async def do_connect(self):
        await self.http_ready.wait()

        stream_id = self._quic.get_next_available_stream_id()
        self.h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"CONNECT"),
                (b":authority", TARGET.encode()),
                (b":scheme", b"NULL"),
                (b":path", b"/")
            ],
            end_stream=True,
        )
        self.transmit()

        await self.response_ready.wait()
        print("CONNECT success" if self.ok else "CONNECT failed")


async def main():
    conf = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    conf.verify_mode = ssl.CERT_NONE  # testing only

    async with connect(
        PROXY_HOST,
        PROXY_PORT,
        configuration=conf,
        create_protocol=Client,
        wait_connected=True,
    ) as client:
        await client.do_connect()
        await asyncio.sleep(1)


asyncio.run(main())

