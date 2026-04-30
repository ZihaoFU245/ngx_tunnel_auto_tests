from __future__ import annotations

import os
from pathlib import Path


AUTO_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.environ.get("NGINX_TEST_REPO_ROOT", AUTO_ROOT.parents[1])).resolve()
DEFAULT_NGINX = Path(os.environ.get("NGINX_TEST_NGINX", REPO_ROOT / "nginx" / "objs" / "nginx")).resolve()
CERT = Path(os.environ.get("NGINX_TEST_CERT", REPO_ROOT / "test" / "certs" / "example.crt")).resolve()
KEY = Path(os.environ.get("NGINX_TEST_KEY", REPO_ROOT / "test" / "certs" / "example.key")).resolve()
AUTH = os.environ.get("NGINX_TEST_PROXY_AUTH", "Basic dXNlcjpwYXNz")
