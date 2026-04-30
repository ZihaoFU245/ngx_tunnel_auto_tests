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
        get_status = await h3.get("127.0.0.1", args.listen_port)
        connect_status = await h3.connect_once("127.0.0.1", args.listen_port, f"127.0.0.1:{args.backend_port}")
        if get_status != 204:
            raise RuntimeError(f"h3 GET returned {get_status}, expected 204")
        if connect_status < 200 or connect_status >= 300:
            raise RuntimeError(f"h3 CONNECT returned {connect_status}")
        print("h3_basic=pass")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/3 GET and CONNECT smoke tests.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    args = parser.parse_args()
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
