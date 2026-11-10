"""每个客户端、每个图层一个缓冲区。三种策略对应三种数据特征：

- ReservoirBuffer（wiki）：量大、单条不重要。每个 tick 最多 cap 条，超出用蓄水池抽样，
  保证样本在时间上均匀，并记录丢弃数
- KeepAllBuffer（usgs）：量小、每条都重要。不丢（设安全上限）
- CoalescingBuffer（opensky）：同一架飞机只关心最新位置。按 key 合并；每个 tick 最多发 cap 条，
  其余留到下个 tick，不丢

无论客户端多慢，每个客户端占用的内存都有上限：wiki <= cap，usgs <= max_items，opensky <= 飞机总数。
"""

from __future__ import annotations

import random
from collections import OrderedDict


class ReservoirBuffer:
    def __init__(self, cap: int, rng: random.Random | None = None) -> None:
        self.cap = cap
        self._rng = rng or random.Random()
        self._items: list = []
        self._seen = 0
        self.dropped_total = 0

    def __len__(self) -> int:
        return len(self._items)

    def offer(self, key: str, row: list) -> None:
        self._seen += 1
        if len(self._items) < self.cap:
            self._items.append(row)
            return
        j = self._rng.randrange(self._seen)
        if j < self.cap:
            self._items[j] = row

    def drain(self) -> tuple[list, int]:
        items, dropped = self._items, max(self._seen - len(self._items), 0)
        self._items, self._seen = [], 0
        self.dropped_total += dropped
        return items, dropped


class KeepAllBuffer:
    def __init__(self, max_items: int = 5000) -> None:
        self._items: list = []
        self._max = max_items
        self.dropped_total = 0

    def __len__(self) -> int:
        return len(self._items)

    def offer(self, key: str, row: list) -> None:
        if len(self._items) >= self._max:
            self._items.pop(0)
            self.dropped_total += 1
        self._items.append(row)

    def drain(self) -> tuple[list, int]:
        items, self._items = self._items, []
        return items, 0


class CoalescingBuffer:
    def __init__(self, cap: int) -> None:
        self.cap = cap
        self._items: OrderedDict[str, list] = OrderedDict()
        self.coalesced_total = 0

    def __len__(self) -> int:
        return len(self._items)

    def offer(self, key: str, row: list) -> None:
        if key in self._items:
            self.coalesced_total += 1
            del self._items[key]  # 移到队尾，保证先到的先发
        self._items[key] = row

    def drain(self) -> tuple[list, int]:
        out = []
        while self._items and len(out) < self.cap:
            _, row = self._items.popitem(last=False)
            out.append(row)
        return out, 0
