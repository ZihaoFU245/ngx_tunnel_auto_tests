#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import h2
from common.backend import start_http_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/2 GET and CONNECT smoke tests.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    args = parser.parse_args()

    with NginxTestServer(args.nginx, NginxConfig(args.listen_port, args.backend_port)) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)
        with h2.connect_tls("127.0.0.1", args.listen_port) as sock:
            h2.request_get(sock, 1, f"127.0.0.1:{args.listen_port}")
            h2.request_connect(sock, 3, f"127.0.0.1:{args.backend_port}")
        print("h2_basic=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
