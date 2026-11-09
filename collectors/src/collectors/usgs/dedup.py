"""采集端去重：同一 id 只有 updated 变大时才再次发送。"""

from __future__ import annotations

from collections import OrderedDict


class SeenCache:
    def __init__(self, max_size: int = 10_000) -> None:
        if max_size <= 0:
            raise ValueError("max_size 必须 > 0")
        self._data: OrderedDict[str, int] = OrderedDict()
        self._max = max_size

    def __len__(self) -> int:
        return len(self._data)

    def should_emit(self, event_id: str, updated_ms: int) -> bool:
        prev = self._data.get(event_id)
        if prev is not None and updated_ms <= prev:
            self._data.move_to_end(event_id)
            return False
        self._data[event_id] = updated_ms
        self._data.move_to_end(event_id)
        if len(self._data) > self._max:
            self._data.popitem(last=False)
        return True
