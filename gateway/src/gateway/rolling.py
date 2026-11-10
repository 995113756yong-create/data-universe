"""滑动窗口计数、延迟分位数、按分钟计数。"""

from __future__ import annotations

from collections import defaultdict, deque


class RollingCounter:
    def __init__(self, horizon_s: int = 120) -> None:
        self.horizon = horizon_s
        self._buckets: dict[str, dict[int, int]] = defaultdict(dict)

    def add(self, key: str, now_s: int, n: int = 1) -> None:
        b = self._buckets[key]
        b[now_s] = b.get(now_s, 0) + n
        if len(b) > self.horizon * 2:
            for k in [k for k in b if k <= now_s - self.horizon]:
                del b[k]

    def total(self, key: str, now_s: int, window_s: int) -> int:
        b = self._buckets.get(key, {})
        lo = now_s - window_s
        return sum(v for k, v in b.items() if lo < k <= now_s)

    def rate(self, key: str, now_s: int, window_s: int = 10) -> float:
        # 不含当前这一秒（还没结束），避免数值偏小
        return round(self.total(key, now_s - 1, window_s) / window_s, 2)


class LagStats:
    """保留最近 N 个延迟样本，计算分位数。"""

    def __init__(self, size: int = 2000) -> None:
        self._samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=size))

    def add(self, key: str, lag_ms: int) -> None:
        if lag_ms >= 0:
            self._samples[key].append(lag_ms)

    def quantiles(self, key: str) -> dict | None:
        s = sorted(self._samples.get(key, ()))
        if not s:
            return None

        def q(p: float) -> int:
            return s[min(len(s) - 1, int(p * len(s)))]

        return {"p50": q(0.5), "p95": q(0.95), "n": len(s)}


class MinuteCounter:
    """按事件时间所在分钟去重计数（verify 用来和 ClickHouse 对数）。"""

    def __init__(self, keep_minutes: int = 30) -> None:
        self.keep = keep_minutes
        self._data: dict[str, dict[int, set]] = defaultdict(dict)

    def add(self, key: str, event_id: str, event_ms: int) -> None:
        minute = event_ms // 60000 * 60000
        d = self._data[key]
        d.setdefault(minute, set()).add(event_id)
        if len(d) > self.keep:
            for k in sorted(d)[: len(d) - self.keep]:
                del d[k]

    def snapshot(self, key: str) -> dict[int, int]:
        return {m: len(ids) for m, ids in sorted(self._data.get(key, {}).items())}
