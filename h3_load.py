#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from common import h3
from common.backend import start_http_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


async def run(args) -> None:
    with NginxTestServer(args.nginx, NginxConfig(args.listen_port, args.backend_port, h3=True)) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)
        await h3.run_connects(
            "127.0.0.1",
            args.listen_port,
            f"127.0.0.1:{args.backend_port}",
            args.requests,
            args.concurrency,
        )
        print(f"h3_load=pass requests={args.requests} concurrency={args.concurrency}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run async concurrent HTTP/3 CONNECT requests.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
