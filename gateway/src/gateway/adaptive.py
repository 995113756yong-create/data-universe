"""客户端渲染负载反馈 -> 动态调整维基点的推送上限（AIMD：慢了减半，快了缓慢回升）。"""

from __future__ import annotations


class AdaptiveCap:
    LOW_FPS = 45.0
    HIGH_FPS = 55.0
    SLOW_SEND_RATIO = 0.8  # 一次发送耗时超过 tick 的 80%，视为网络或客户端跟不上

    def __init__(self, initial: int, minimum: int) -> None:
        self.max = initial
        self.min = minimum
        self.value = initial

    def on_fps(self, fps: float) -> int:
        if fps < self.LOW_FPS:
            self.value = max(self.min, self.value // 2)
        elif fps >= self.HIGH_FPS:
            self.value = min(self.max, int(self.value * 1.25) + 1)
        return self.value

    def on_send(self, send_ms: float, tick_ms: float) -> int:
        if send_ms > tick_ms * self.SLOW_SEND_RATIO:
            self.value = max(self.min, self.value // 2)
        return self.value
