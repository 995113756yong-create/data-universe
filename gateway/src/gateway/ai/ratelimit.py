"""提问限流：每个客户端每分钟 N 次 + 全局每日上限（保护 API 费用）。"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_min: int, per_day: int, clock=time.time) -> None:
        self.per_min = per_min
        self.per_day = per_day
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._day_count = 0

    def check(self, client: str) -> str | None:
        """允许返回 None 并计数；拒绝返回原因。"""
        now = self._clock()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day != self._day:
            self._day, self._day_count = day, 0
        if self._day_count >= self.per_day:
            return "今日提问次数已用完（全局上限），明天再来"
        q = self._hits[client]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_min:
            return f"提问太频繁，每分钟最多 {self.per_min} 次"
        q.append(now)
        self._day_count += 1
        if len(self._hits) > 10_000:  # 防止内存无限增长
            self._hits = defaultdict(
                deque, {k: v for k, v in self._hits.items() if v and now - v[-1] <= 60}
            )
        return None
