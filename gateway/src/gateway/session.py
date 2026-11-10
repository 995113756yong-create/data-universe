"""单个浏览器连接：按 tick 合包推送，订阅过滤，背压降级。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import orjson

from gateway.adaptive import AdaptiveCap
from gateway.buffers import CoalescingBuffer, KeepAllBuffer, ReservoirBuffer
from gateway.config import LAYERS, GatewaySettings
from gateway.protocol import PROTOCOL_VERSION, dumps

log = logging.getLogger("gateway.session")


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class ClientSession:
    def __init__(self, ws, settings: GatewaySettings) -> None:
        self.ws = ws
        self.s = settings
        self.layers: set[str] = set(LAYERS)
        self.cap = AdaptiveCap(settings.wiki_cap, settings.wiki_cap_min)
        self.buffers = {
            "wiki": ReservoirBuffer(self.cap.value),
            "usgs": KeepAllBuffer(),
            "opensky": CoalescingBuffer(settings.flight_cap),
        }
        self._control: asyncio.Queue[str] = asyncio.Queue(maxsize=20)
        self.batches_sent = 0
        self.skipped_ticks = 0
        self.last_fps: float | None = None

    # ---------- 由 Hub 调用（同一个事件循环内，无需加锁） ----------
    def offer(self, layer: str, key: str, row: list) -> None:
        if layer in self.layers:
            self.buffers[layer].offer(key, row)

    def push_control(self, msg: dict) -> None:
        """metrics / warn 等控制消息。队列满时丢弃最旧的一条（metrics 只关心最新值）。"""
        data = dumps(msg)
        if self._control.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._control.get_nowait()
        self._control.put_nowait(data)

    # ---------- 纯逻辑，便于测试 ----------
    def build_batch(self) -> dict | None:
        rows, dropped = {}, {}
        for layer, buf in self.buffers.items():
            items, d = buf.drain()
            if items:
                rows[layer] = items
            if d:
                dropped[layer] = d
        if not rows and not dropped:
            return None
        return {
            "t": "batch",
            "server_ms": now_ms(),
            "rows": rows,
            "dropped": dropped,
            "cap": {"wiki": self.cap.value},
            "pending": {"opensky": len(self.buffers["opensky"])},
        }

    def handle_client_message(self, text: str) -> None:
        try:
            msg = orjson.loads(text)
        except orjson.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("t") == "subscribe" and isinstance(msg.get("layers"), list):
            self.layers = {x for x in msg["layers"] if x in LAYERS}
            for layer in LAYERS:
                if layer not in self.layers:
                    self.buffers[layer].drain()
        elif msg.get("t") == "load":
            try:
                fps = float(msg.get("fps"))
            except (TypeError, ValueError):
                return
            self.last_fps = fps
            self.buffers["wiki"].cap = self.cap.on_fps(fps)

    # ---------- IO ----------
    async def send_hello(self) -> None:
        await self.ws.send_text(
            dumps(
                {
                    "t": "hello",
                    "v": PROTOCOL_VERSION,
                    "server_ms": now_ms(),
                    "tick_ms": self.s.tick_ms,
                    "layers": list(LAYERS),
                }
            )
        )

    async def send_raw(self, data: str) -> None:
        await self.ws.send_text(data)

    async def send_loop(self) -> None:
        loop = asyncio.get_running_loop()
        tick = self.s.tick_ms / 1000
        next_tick = loop.time()
        while True:
            next_tick += tick
            await asyncio.sleep(max(0.0, next_tick - loop.time()))
            while not self._control.empty():
                await self.ws.send_text(self._control.get_nowait())
            batch = self.build_batch()
            if batch is not None:
                t0 = loop.time()
                await self.ws.send_text(dumps(batch))
                self.batches_sent += 1
                send_ms = (loop.time() - t0) * 1000
                self.buffers["wiki"].cap = self.cap.on_send(send_ms, self.s.tick_ms)
            lag = loop.time() - next_tick
            if lag > tick:
                # 发送太慢错过了 tick：直接对齐到现在，错过的数据留在缓冲区里合并进下一包
                self.skipped_ticks += int(lag // tick)
                next_tick = loop.time()

    async def recv_loop(self) -> None:
        while True:
            text = await self.ws.receive_text()
            self.handle_client_message(text)
