#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import h2
from common.backend import start_echo_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/2 padding negotiation and relay test.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    args = parser.parse_args()

    start_echo_backend(args.backend_port)
    config = NginxConfig(args.listen_port, args.backend_port, padding=True, root_response=False)
    with NginxTestServer(args.nginx, config):
        h2.check_padding_echo("127.0.0.1", args.listen_port, f"127.0.0.1:{args.backend_port}")
        print("h2_padding_basic=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
