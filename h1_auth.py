#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
import textwrap
from pathlib import Path

from common import h1
from common.backend import start_http_backend
from common.nginx import NginxConfig, NginxTestServer
from common.paths import DEFAULT_NGINX, TUNNEL_MODULE


GOOD_AUTH = "Basic dXNlcjpwYXNz"
BAD_AUTH = "Basic dXNlcjpiYWQ="


def connect_response(port: int, backend_port: int, auth: str | None) -> bytes:
    authority = f"127.0.0.1:{backend_port}"
    lines = [
        f"CONNECT {authority} HTTP/1.1",
        f"Host: {authority}",
        "Connection: close",
    ]

    if auth is not None:
        lines.insert(2, f"Proxy-Authorization: {auth}")

    payload = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
    return h1.request("127.0.0.1", port, payload)


def status(response: bytes) -> int:
    return int(response.split(b" ", 2)[1])


def assert_header(response: bytes, header: bytes) -> None:
    if header.lower() not in response.lower():
        raise RuntimeError(f"missing header {header!r} in {response!r}")


def check_auth(args: argparse.Namespace, config: NginxConfig,
               expected_failure: int, expected_header: bytes | None) -> None:
    with NginxTestServer(args.nginx, config) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)

        response = connect_response(args.listen_port, args.backend_port, None)
        if status(response) != expected_failure:
            raise RuntimeError(f"CONNECT without auth returned {response!r}")
        if expected_header is not None:
            assert_header(response, expected_header)

        response = connect_response(args.listen_port, args.backend_port, BAD_AUTH)
        if status(response) != expected_failure:
            raise RuntimeError(f"CONNECT with bad auth returned {response!r}")
        if expected_header is not None:
            assert_header(response, expected_header)

        response = connect_response(args.listen_port, args.backend_port, GOOD_AUTH)
        if response.startswith(b"HTTP/"):
            code = status(response)
            if code == expected_failure:
                raise RuntimeError(f"CONNECT with good auth was rejected: {response!r}")


def check_user_file_is_used(args: argparse.Namespace) -> None:
    config = NginxConfig(
        args.listen_port,
        args.backend_port,
        root_response=False,
        auth_user_file_line="other:$apr1$tunnelsa$H1PAZkbgAv289lfmsboYd.",
    )

    with NginxTestServer(args.nginx, config) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)

        response = connect_response(args.listen_port, args.backend_port, GOOD_AUTH)
        if status(response) != 407:
            raise RuntimeError(f"CONNECT ignored configured user file: {response!r}")
        assert_header(response, b"Proxy-Authenticate: Basic realm=\"proxy\"")


def check_empty_hash_does_not_crash(args: argparse.Namespace) -> None:
    config = NginxConfig(
        args.listen_port,
        args.backend_port,
        root_response=False,
        auth_user_file_line="user:",
    )

    with NginxTestServer(args.nginx, config) as server:
        start_http_backend(server.processes, server.workdir, args.backend_port)

        response = connect_response(args.listen_port, args.backend_port, GOOD_AUTH)
        if status(response) != 407:
            raise RuntimeError(f"empty hash did not fail auth cleanly: {response!r}")
        assert_header(response, b"Proxy-Authenticate: Basic realm=\"proxy\"")


def check_invalid_failure_code(args: argparse.Namespace) -> None:
    workdir = Path(tempfile.mkdtemp(prefix="tunnel-invalid-auth-code-"))
    user_file = workdir / "htpasswd"
    user_file.write_text("user:$apr1$tunnelsa$H1PAZkbgAv289lfmsboYd.\n",
                         encoding="ascii")

    conf = workdir / "nginx.conf"
    load_module = (
        f"load_module {TUNNEL_MODULE};"
        if TUNNEL_MODULE.exists()
        else ""
    )
    conf.write_text(
        textwrap.dedent(
            f"""
            daemon off;
            master_process off;
            {load_module}
            worker_processes 1;
            pid {workdir}/nginx.pid;
            error_log stderr notice;

            events {{
                worker_connections 128;
            }}

            http {{
                server {{
                    listen 127.0.0.1:{args.listen_port};
                    tunnel_pass;
                    tunnel_proxy_auth_user_file {user_file};
                    tunnel_probe_resistance on;
                    tunnel_auth_failure_code 429;
                }}
            }}
            """
        ),
        encoding="ascii",
    )

    proc = subprocess.run(
        [args.nginx, "-t", "-c", str(conf), "-p", str(workdir), "-e", "stderr"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    output = proc.stdout + proc.stderr
    if proc.returncode == 0 or b"invalid tunnel_auth_failure_code" not in output:
        raise RuntimeError(f"invalid tunnel_auth_failure_code was accepted: {output!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTTP/1.1 tunnel auth tests.")
    parser.add_argument("--nginx", default=str(DEFAULT_NGINX))
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    args = parser.parse_args()

    check_auth(
        args,
        NginxConfig(args.listen_port, args.backend_port, root_response=False),
        407,
        b"Proxy-Authenticate: Basic realm=\"proxy\"",
    )

    check_auth(
        args,
        NginxConfig(args.listen_port, args.backend_port,
                    auth_failure_code=404, root_response=False),
        407,
        b"Proxy-Authenticate: Basic realm=\"proxy\"",
    )

    check_auth(
        args,
        NginxConfig(args.listen_port, args.backend_port,
                    probe_resistance=True, root_response=False),
        405,
        b"Allow: GET, POST, HEAD, OPTIONS",
    )

    check_auth(
        args,
        NginxConfig(args.listen_port, args.backend_port,
                    probe_resistance=True, auth_failure_code=403,
                    root_response=False),
        403,
        None,
    )

    check_auth(
        args,
        NginxConfig(args.listen_port, args.backend_port,
                    probe_resistance=True, auth_failure_code=404,
                    root_response=False),
        404,
        None,
    )

    check_user_file_is_used(args)
    check_empty_hash_does_not_crash(args)
    check_invalid_failure_code(args)

    print("h1_auth=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
