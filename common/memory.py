from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from .process import rss_kb


def run_memory_rounds(
    *,
    pid: int,
    rounds: int,
    requests: int,
    runner: Callable[[int], None],
) -> int:
    baseline = rss_kb(pid)
    previous = baseline
    increases: list[int] = []
    print(f"nginx_pid={pid}")
    print(f"requests_per_round={requests}")
    print(f"rounds={rounds}")
    print(f"baseline_rss_kb={baseline}")
    print("round rss_before_kb rss_after_kb delta_round_kb delta_total_kb")
    for round_no in range(1, rounds + 1):
        before = rss_kb(pid)
        runner(requests)
        time.sleep(1)
        after = rss_kb(pid)
        increases.append(after - previous)
        previous = after
        print(f"{round_no} {before} {after} {after - before} {after - baseline}", flush=True)
    post_warmup = increases[1:]
    if len(post_warmup) >= 2 and all(delta > 0 for delta in post_warmup):
        print("result=possible_leak repeated RSS increase after warmup")
        return 2
    print("result=pass RSS did not increase every post-warmup round")
    return 0


def run_async_memory_rounds(
    *,
    pid: int,
    rounds: int,
    requests: int,
    runner: Callable[[int], object],
) -> int:
    return run_memory_rounds(
        pid=pid,
        rounds=rounds,
        requests=requests,
        runner=lambda count: asyncio.run(runner(count)),
    )
