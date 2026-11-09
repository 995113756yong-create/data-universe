"""指数退避（full jitter）。"""

from __future__ import annotations

import random
from collections.abc import Iterator


def backoff_delays(
    base: float = 1.0,
    factor: float = 2.0,
    cap: float = 60.0,
    rng: random.Random | None = None,
) -> Iterator[float]:
    """第 n 次返回 uniform(0, min(cap, base * factor**n))，到达 cap 后不再增长。"""
    if base <= 0 or factor < 1 or cap < base:
        raise ValueError("要求 base > 0, factor >= 1, cap >= base")
    rng = rng or random.Random()
    ceiling = base
    while True:
        yield rng.uniform(0, ceiling)
        ceiling = min(cap, ceiling * factor)
