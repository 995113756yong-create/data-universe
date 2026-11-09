"""采集器计数与周期性日志输出（JSON 行）。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("collectors.metrics")


@dataclass
class Counter:
    name: str
    sent: int = 0
    filtered: int = 0
    dropped: int = 0
    errors: int = 0
    _last_sent: int = 0
    _last_ts: float = field(default_factory=time.monotonic)

    def on_error(self, exc: BaseException) -> None:
        self.errors += 1
        log.warning("%s delivery error: %r", self.name, exc)

    def snapshot(self) -> dict:
        now = time.monotonic()
        elapsed = max(now - self._last_ts, 1e-6)
        rate = (self.sent - self._last_sent) / elapsed
        self._last_sent, self._last_ts = self.sent, now
        return {
            "collector": self.name,
            "sent": self.sent,
            "filtered": self.filtered,
            "dropped": self.dropped,
            "errors": self.errors,
            "rate_per_s": round(rate, 2),
        }


async def report_forever(counters: list[Counter], interval: float = 30.0) -> None:
    while True:
        await asyncio.sleep(interval)
        for c in counters:
            log.info(json.dumps(c.snapshot(), ensure_ascii=False))
