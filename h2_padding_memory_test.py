#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import h2
from common.backend import start_echo_backend
from common.memory import run_async_memory_rounds
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/2 padding memory regression test.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    args = parser.parse_args()

    start_echo_backend(args.backend_port)
    config = NginxConfig(args.listen_port, args.backend_port, padding=True, root_response=False)
    with NginxTestServer(args.nginx, config) as server:
        return run_async_memory_rounds(
            pid=server.pid,
            rounds=args.rounds,
            requests=args.requests,
            runner=lambda count: h2.run_padding_connects(
                "127.0.0.1",
                args.listen_port,
                f"127.0.0.1:{args.backend_port}",
                count,
                args.concurrency,
            ),
        )


if __name__ == "__main__":
    raise SystemExit(main())
