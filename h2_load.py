#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from common import h2
from common.backend import start_echo_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


async def run(args) -> None:
    config = NginxConfig(args.listen_port, args.backend_port, root_response=False)
    start_echo_backend(args.backend_port)
    with NginxTestServer(args.nginx, config) as server:
        await h2.run_connects(
            "127.0.0.1",
            args.listen_port,
            f"127.0.0.1:{args.backend_port}",
            args.requests,
            args.concurrency,
        )
        print(f"h2_load=pass requests={args.requests} concurrency={args.concurrency}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated HTTP/2 CONNECT requests.")
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
