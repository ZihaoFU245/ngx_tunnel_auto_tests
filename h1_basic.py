#!/usr/bin/env python3
from __future__ import annotations

import argparse

from common import h1
from common.backend import start_http_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import AUTH, DEFAULT_NGINX


def connect_response(port: int, backend_port: int) -> bytes:
    authority = f"127.0.0.1:{backend_port}"
    payload = (
        f"CONNECT {authority} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        f"Proxy-Authorization: {AUTH}\r\n"
        "\r\n"
    ).encode("ascii")
    return h1.request("127.0.0.1", port, payload)


def status(response: bytes) -> int:
    return int(response.split(b" ", 2)[1])


def check_acl_deny_closes(args: argparse.Namespace) -> None:
    config = NginxConfig(args.listen_port, args.backend_port, acl_deny=True,
                         root_response=False)

    with NginxTestServer(args.nginx, config) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)

        response = connect_response(args.listen_port, args.backend_port)
        if status(response) != 403:
            raise RuntimeError(f"ACL-denied CONNECT returned {response!r}")
        if b"connection: keep-alive" in response.lower():
            raise RuntimeError(f"ACL-denied CONNECT kept alive: {response!r}")


def check_acl_deny_not_bypassed_by_satisfy_any(args: argparse.Namespace) -> None:
    config = NginxConfig(
        args.listen_port,
        args.backend_port,
        acl_deny=True,
        satisfy_any_allow_all=True,
        root_response=False,
    )

    with NginxTestServer(args.nginx, config) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)

        response = connect_response(args.listen_port, args.backend_port)
        if status(response) != 403:
            raise RuntimeError(
                f"ACL-denied CONNECT was bypassed by satisfy any: {response!r}"
            )


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

    check_acl_deny_closes(args)
    check_acl_deny_not_bypassed_by_satisfy_any(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
