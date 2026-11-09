from __future__ import annotations

import asyncio
import time


def now_ms() -> int:
    """当前 UTC epoch 毫秒。"""
    return time.time_ns() // 1_000_000


async def sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    """睡眠 seconds 秒；期间收到停止信号立即返回。"""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(seconds, 0))
    except TimeoutError:
        pass
