from __future__ import annotations

import os
from pathlib import Path


AUTO_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.environ.get("NGINX_TEST_REPO_ROOT", AUTO_ROOT.parents[1])).resolve()
DEFAULT_NGINX = Path(os.environ.get("NGINX_TEST_NGINX", REPO_ROOT / "nginx" / "objs" / "nginx")).resolve()
TUNNEL_MODULE = Path(os.environ.get("NGINX_TEST_TUNNEL_MODULE", REPO_ROOT / "nginx" / "objs" / "ngx_http_tunnel_module.so")).resolve()
CERT = Path(os.environ.get("NGINX_TEST_CERT", AUTO_ROOT / "certs" / "example.crt")).resolve()
KEY = Path(os.environ.get("NGINX_TEST_KEY", AUTO_ROOT / "certs" / "example.key")).resolve()
AUTH = os.environ.get("NGINX_TEST_PROXY_AUTH", "Basic dXNlcjpwYXNz")
