#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import h1
from common.backend import start_http_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/1.1 GET and CONNECT smoke tests.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    args = parser.parse_args()

    with NginxTestServer(args.nginx, NginxConfig(args.listen_port, args.backend_port)) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)
        get_status = h1.get("127.0.0.1", args.listen_port)
        connect_status = h1.connect("127.0.0.1", args.listen_port, f"127.0.0.1:{args.backend_port}")
        if get_status != 204:
            raise RuntimeError(f"h1 GET returned {get_status}, expected 204")
        if connect_status < 200 or connect_status >= 300:
            raise RuntimeError(f"h1 CONNECT returned {connect_status}")
        print("h1_basic=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
