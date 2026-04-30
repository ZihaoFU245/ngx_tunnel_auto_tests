from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from .backend import wait_tcp_port
from .certs import ensure_certificate
from .paths import CERT, KEY, DEFAULT_NGINX
from .process import ProcessSet


@dataclass
class NginxConfig:
    listen_port: int
    backend_port: int
    h3: bool = False
    acl_deny: bool = False
    connect_timeout: bool = False
    padding: bool = False
    root_response: bool = True


class NginxTestServer:
    def __init__(self, nginx: str | os.PathLike[str] = DEFAULT_NGINX, config: NginxConfig | None = None) -> None:
        self.nginx = Path(nginx).expanduser().resolve()
        self.config = config or NginxConfig(listen_port=3128, backend_port=18080)
        self.workdir = Path(tempfile.mkdtemp(prefix="tunnel-auto-"))
        self.processes = ProcessSet()
        self.proc: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "NginxTestServer":
        ensure_certificate()
        for name in ["client_body", "proxy", "fastcgi", "uwsgi", "scgi"]:
            (self.workdir / name).mkdir(parents=True, exist_ok=True)
        conf = self.write_conf()
        self.proc = self.processes.start(
            [self.nginx, "-c", conf, "-p", self.workdir, "-e", "stderr"],
            cwd=self.workdir,
        )
        wait_tcp_port(self.config.listen_port)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.processes.cleanup()

    @property
    def pid(self) -> int:
        if self.proc is None:
            raise RuntimeError("nginx is not running")
        return self.proc.pid

    def write_conf(self) -> Path:
        acl = ""
        if self.config.acl_deny:
            acl = textwrap.dedent(
                f"""
                upstream denied {{
                    server 127.0.0.1:{self.config.backend_port};
                }}
                """
            )

        acl_directive = "tunnel_acl_deny denied;" if self.config.acl_deny else ""
        quic_listen = (
            f"listen 127.0.0.1:{self.config.listen_port} quic reuseport;\n"
            "                http3 on;\n"
            "                http3_max_concurrent_streams 512;\n"
            if self.config.h3
            else ""
        )
        resolver = "resolver 1.1.1.1 8.8.8.8;"
        padding_directive = "tunnel_padding on;" if self.config.padding else "tunnel_padding off;"
        location = (
            textwrap.dedent(
                """
                location / {
                    return 204;
                }
                """
            )
            if self.config.root_response
            else ""
        )
        conf = textwrap.dedent(
            f"""
            daemon off;
            master_process off;
            worker_processes 1;
            pid {self.workdir}/nginx.pid;
            error_log stderr notice;

            events {{
                worker_connections 8192;
            }}

            http {{
                access_log off;
                keepalive_requests 100000;
                client_body_temp_path {self.workdir}/client_body;
                proxy_temp_path {self.workdir}/proxy;
                fastcgi_temp_path {self.workdir}/fastcgi;
                uwsgi_temp_path {self.workdir}/uwsgi;
                scgi_temp_path {self.workdir}/scgi;

                {acl}

                server {{
                    listen 127.0.0.1:{self.config.listen_port} ssl;
                    {quic_listen}
                    ssl_certificate {CERT};
                    ssl_certificate_key {KEY};
                    ssl_session_cache off;
                    ssl_session_tickets off;
                    http2 on;
                    {resolver}

                    {location}

                    tunnel_pass;
                    tunnel_auth_username user;
                    tunnel_auth_password pass;
                    {acl_directive}
                    tunnel_buffer_size 16k;
                    tunnel_connect_timeout 500ms;
                    tunnel_idle_timeout 2s;
                    tunnel_probe_resistance off;
                    {padding_directive}
                }}
            }}
            """
        )
        path = self.workdir / "nginx.conf"
        path.write_text(conf, encoding="ascii")
        return path
