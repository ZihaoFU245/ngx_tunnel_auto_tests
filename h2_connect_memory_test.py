#!/usr/bin/env python3
import argparse
import atexit
import os
import signal
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import textwrap
import time


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_NGINX = os.path.join(ROOT, "nginx", "objs", "nginx")
CERT = os.path.join(ROOT, "test", "certs", "example.crt")
KEY = os.path.join(ROOT, "test", "certs", "example.key")
AUTH = "Basic dXNlcjpwYXNz"


children = []


def cleanup():
    for proc in reversed(children):
        if proc.poll() is not None:
            continue
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.time() + 3
    for proc in reversed(children):
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)

    for proc in reversed(children):
        if proc.poll() is not None:
            continue
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


atexit.register(cleanup)


def hpack_int(value, prefix_bits, first):
    max_prefix = (1 << prefix_bits) - 1
    if value < max_prefix:
        return bytes([first | value])

    out = bytearray([first | max_prefix])
    value -= max_prefix
    while value >= 128:
        out.append((value & 0x7f) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def hpack_string(value):
    data = value.encode("ascii")
    return hpack_int(len(data), 7, 0) + data


def literal_indexed_name(index, value):
    return hpack_int(index, 4, 0) + hpack_string(value)


def literal_new_name(name, value):
    return b"\x00" + hpack_string(name) + hpack_string(value)


def frame(frame_type, flags, stream_id, payload=b""):
    return (
        len(payload).to_bytes(3, "big")
        + bytes([frame_type, flags])
        + struct.pack("!I", stream_id & 0x7fffffff)
        + payload
    )


def read_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def read_frame(sock):
    header = read_exact(sock, 9)
    if header is None:
        return None
    length = int.from_bytes(header[:3], "big")
    payload = read_exact(sock, length)
    if payload is None:
        return None
    return header[3], header[4], struct.unpack("!I", header[5:9])[0], payload


def h2_connect(host, port):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2"])

    raw = socket.create_connection((host, port), timeout=5)
    sock = ctx.wrap_socket(raw, server_hostname=host)
    sock.settimeout(5)

    if sock.selected_alpn_protocol() != "h2":
        raise RuntimeError("h2 was not negotiated")

    sock.sendall(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
    sock.sendall(frame(0x4, 0x0, 0, b""))
    return sock


def do_connect_request(sock, stream_id, authority, reset_after_headers):
    block = b"".join(
        [
            literal_indexed_name(2, "CONNECT"),
            literal_indexed_name(1, authority),
            literal_new_name("proxy-authorization", AUTH),
        ]
    )
    sock.sendall(frame(0x1, 0x5, stream_id, block))

    got_headers = False
    deadline = time.time() + 5

    while time.time() < deadline:
        item = read_frame(sock)
        if item is None:
            raise RuntimeError("connection closed while waiting for response")

        frame_type, flags, sid, payload = item

        if frame_type == 0x4 and not (flags & 0x1):
            sock.sendall(frame(0x4, 0x1, 0))
            continue

        if sid != stream_id:
            continue

        if frame_type == 0x1:
            got_headers = True

        if flags & 0x1:
            return

        if reset_after_headers and got_headers and frame_type == 0x1:
            # The tunnel is established. Close the client stream cleanly so
            # nginx must finalize and free this request before the next round.
            sock.sendall(frame(0x3, 0x0, stream_id, struct.pack("!I", 0)))
            return

    raise TimeoutError(f"stream {stream_id} did not receive a response")


def wait_port(port, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"port {port} did not open")


def rss_kb(pid):
    with open(f"/proc/{pid}/status", "r", encoding="ascii") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise RuntimeError(f"VmRSS not found for pid {pid}")


def write_conf(workdir, listen_port, backend_port, scenario):
    acl = ""
    if scenario == "acl-deny":
        acl = textwrap.dedent(
            f"""
            upstream denied {{
                server 127.0.0.1:{backend_port};
            }}
            """
        )

    acl_directive = "tunnel_acl_deny denied;" if scenario == "acl-deny" else ""

    conf = textwrap.dedent(
        f"""
        daemon off;
        master_process off;
        worker_processes 1;
        pid {workdir}/nginx.pid;
        error_log {workdir}/error.log notice;

        events {{
            worker_connections 4096;
        }}

        http {{
            access_log off;
            client_body_temp_path {workdir}/client_body;
            proxy_temp_path {workdir}/proxy;
            fastcgi_temp_path {workdir}/fastcgi;
            uwsgi_temp_path {workdir}/uwsgi;
            scgi_temp_path {workdir}/scgi;

            {acl}

            server {{
                listen 127.0.0.1:{listen_port} ssl;
                ssl_certificate {CERT};
                ssl_certificate_key {KEY};
                ssl_session_cache off;
                ssl_session_tickets off;
                http2 on;
                resolver 1.1.1.1 8.8.8.8;

                tunnel_pass;
                tunnel_auth_username user;
                tunnel_auth_password pass;
                {acl_directive}
                tunnel_buffer_size 16k;
                tunnel_connect_timeout 60s;
                tunnel_idle_timeout 2s;
                tunnel_probe_resistance off;
            }}
        }}
        """
    )

    path = os.path.join(workdir, "nginx.conf")
    with open(path, "w", encoding="ascii") as f:
        f.write(conf)
    return path


def start_process(args, **kwargs):
    proc = subprocess.Popen(args, start_new_session=True, **kwargs)
    children.append(proc)
    return proc


def run_round(host, port, authority, requests, reuse_connection, reset_after_headers):
    if reuse_connection:
        sock = h2_connect(host, port)
        try:
            for i in range(requests):
                do_connect_request(
                    sock, 1 + i * 2, authority, reset_after_headers
                )
        finally:
            sock.close()
        return

    for _ in range(requests):
        sock = h2_connect(host, port)
        try:
            do_connect_request(sock, 1, authority, reset_after_headers)
        finally:
            sock.close()


def main():
    parser = argparse.ArgumentParser(
        description="Run repeated HTTP/2 CONNECT rounds and report nginx RSS."
    )
    parser.add_argument("--nginx", default=DEFAULT_NGINX)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--listen-port", type=int, default=3128)
    parser.add_argument("--backend-port", type=int, default=18080)
    parser.add_argument(
        "--scenario", choices=["success", "acl-deny"], default="success"
    )
    parser.add_argument(
        "--reuse-connection",
        action="store_true",
        help="send all CONNECT streams in a round on one HTTP/2 connection",
    )
    parser.add_argument(
        "--reset-after-headers",
        action="store_true",
        help="send RST_STREAM as soon as CONNECT response headers arrive",
    )
    args = parser.parse_args()

    workdir = tempfile.mkdtemp(prefix="tunnel-h2-memory-")
    for name in ["client_body", "proxy", "fastcgi", "uwsgi", "scgi"]:
        os.makedirs(os.path.join(workdir, name), exist_ok=True)

    conf = write_conf(workdir, args.listen_port, args.backend_port, args.scenario)

    backend_log = open(os.path.join(workdir, "backend.log"), "wb")
    nginx_log = open(os.path.join(workdir, "nginx.stdout"), "wb")

    try:
        backend = start_process(
            [
                sys.executable,
                "-m",
                "http.server",
                str(args.backend_port),
                "--bind",
                "127.0.0.1",
            ],
            cwd=workdir,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
        )
        wait_port(args.backend_port)

        nginx = start_process(
            [args.nginx, "-c", conf, "-p", workdir, "-e", os.path.join(workdir, "error.log")],
            cwd=workdir,
            stdout=nginx_log,
            stderr=subprocess.STDOUT,
        )
        wait_port(args.listen_port)

        authority = f"127.0.0.1:{args.backend_port}"
        baseline = rss_kb(nginx.pid)
        previous = baseline

        print(f"scenario={args.scenario}")
        print(f"nginx_pid={nginx.pid}")
        print(f"requests_per_round={args.requests}")
        print(f"rounds={args.rounds}")
        print(f"reuse_connection={args.reuse_connection}")
        print(f"reset_after_headers={args.reset_after_headers}")
        print(f"baseline_rss_kb={baseline}")
        print("round rss_before_kb rss_after_kb delta_round_kb delta_total_kb")

        increases = []
        for round_no in range(1, args.rounds + 1):
            before = rss_kb(nginx.pid)
            run_round(
                "127.0.0.1",
                args.listen_port,
                authority,
                args.requests,
                args.reuse_connection,
                args.reset_after_headers,
            )
            time.sleep(1)
            after = rss_kb(nginx.pid)
            delta_round = after - before
            delta_total = after - baseline
            increases.append(after - previous)
            previous = after
            print(
                f"{round_no} {before} {after} {delta_round} {delta_total}",
                flush=True,
            )

        if all(delta > 0 for delta in increases[1:]):
            print("result=possible_leak repeated RSS increase after warmup")
            return 2

        print("result=pass RSS did not increase every post-warmup round")
        return 0

    finally:
        backend_log.close()
        nginx_log.close()
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
