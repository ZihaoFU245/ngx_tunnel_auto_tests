from __future__ import annotations

import subprocess

from .paths import CERT, KEY


def ensure_certificate() -> None:
    CERT.parent.mkdir(parents=True, exist_ok=True)
    if CERT.exists() and KEY.exists():
        return
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(KEY),
            "-out",
            str(CERT),
            "-subj",
            "/CN=localhost",
            "-days",
            "1",
        ],
        check=True,
    )
