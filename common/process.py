from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path


class ProcessSet:
    def __init__(self) -> None:
        self._children: list[subprocess.Popen[bytes]] = []

    def start(
        self,
        args: Sequence[str | os.PathLike[str]],
        *,
        cwd: str | os.PathLike[str] | None = None,
    ) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            [str(arg) for arg in args],
            cwd=cwd,
            start_new_session=True,
        )
        self._children.append(proc)
        return proc

    def cleanup(self) -> None:
        for proc in reversed(self._children):
            if proc.poll() is not None:
                continue
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)

        deadline = time.monotonic() + 3
        for proc in reversed(self._children):
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)

        for proc in reversed(self._children):
            if proc.poll() is not None:
                continue
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)


def rss_kb(pid: int) -> int:
    status = Path("/proc") / str(pid) / "status"
    lines = status.read_text(encoding="ascii", errors="replace").splitlines()
    for line in lines:
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    state = next((line for line in lines if line.startswith("State:")), "State: unknown")
    raise RuntimeError(f"VmRSS not present for pid {pid}; {state}")
