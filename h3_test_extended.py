import asyncio
import ssl

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated


PROXY_HOST = "mirror.zihaofu245.me"
PROXY_PORT = 443

# remote target you want nginx to relay to
TARGET = "example.com:80"

# path that hits your nginx tunnel location
TUNNEL_PATH = "/"

class Client(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.h3 = None
        self.http_ready = asyncio.Event()
        self.response_ready = asyncio.Event()
        self.done = asyncio.Event()
        self.ok = False
        self.stream_id = None

    def quic_event_received(self, event):
        if isinstance(event, ProtocolNegotiated) and event.alpn_protocol in H3_ALPN:
            self.h3 = H3Connection(self._quic)
            self.http_ready.set()
            return

        if self.h3 is None:
            return

        for ev in self.h3.handle_event(event):
            if isinstance(ev, HeadersReceived):
                print("CONNECT response headers:")
                for k, v in ev.headers:
                    print(k.decode(errors="ignore"), v.decode(errors="ignore"))

                for k, v in ev.headers:
                    if k == b":status" and v.startswith(b"2"):
                        self.ok = True

                self.response_ready.set()

            elif isinstance(ev, DataReceived):
                if ev.data:
                    print(ev.data.decode(errors="ignore"), end="")
                if ev.stream_ended:
                    self.done.set()

    async def do_test(self):
        await self.http_ready.wait()

        self.stream_id = self._quic.get_next_available_stream_id()

        self.h3.send_headers(
            stream_id=self.stream_id,
            headers=[
                (b":method", b"CONNECT"),
                (b":authority", TARGET.encode()),
                (b":scheme", b"NULL"),
                (b":path", TUNNEL_PATH.encode()),
            ],
            end_stream=False,
        )
        self.transmit()

        try:
            await asyncio.wait_for(self.response_ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            print("No CONNECT response before client FIN.")
            print("That means nginx is likely waiting for end-of-stream before replying.")
            print("Then this code path cannot act as a real relay tunnel yet.")
            self.done.set()
            return

        if not self.ok:
            print("CONNECT failed")
            self.done.set()
            return

        print("CONNECT success\n")

        # send plain HTTP to example.com:80 through the tunnel
        req = (
            "GET / HTTP/1.1\r\n"
            "Host: example.com\r\n"
            "User-Agent: h3-connect-test/1.0\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode()

        self.h3.send_data(
            stream_id=self.stream_id,
            data=req,
            end_stream=False,
        )
        self.transmit()


async def main():
    conf = QuicConfiguration(is_client=True, alpn_protocols=H3_ALPN)
    conf.verify_mode = ssl.CERT_NONE

    async with connect(
        PROXY_HOST,
        PROXY_PORT,
        configuration=conf,
        create_protocol=Client,
        wait_connected=True,
    ) as client:
        await client.do_test()
        await asyncio.wait_for(client.done.wait(), timeout=10)


asyncio.run(main())
