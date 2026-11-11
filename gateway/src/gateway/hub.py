"""Hub：消费 evt.unified，统计指标，把事件分发给所有在线客户端。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable

from gateway.alerts import AlertStore, load_centroids, normalize
from gateway.clickhouse import ClickHouse
from gateway.config import LAYERS, GatewaySettings
from gateway.protocol import dumps, encode
from gateway.rolling import LagStats, MinuteCounter, RollingCounter
from gateway.session import ClientSession

log = logging.getLogger("gateway.hub")

# 超过该时长没有新事件，数据源状态记为 stale。地震本身稀少，阈值放宽。
STALE_AFTER_MS = {"wiki": 60_000, "usgs": 3 * 3600_000}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class Hub:
    def __init__(self, settings: GatewaySettings, ch: ClickHouse | None) -> None:
        self.s = settings
        self.ch = ch
        self.clients: set[ClientSession] = set()
        self.rolling = RollingCounter()
        self.lag = LagStats()
        self.minutes = MinuteCounter()
        self.flights: dict[str, int] = {}
        self.last_event: dict[str, dict] = {}
        self.consumed = 0
        self.started_ms = now_ms()
        self.kafka_ok = False
        self.ch_ok = False
        self._panel: dict = {}
        self._panel_at = 0.0
        self._panel_lock = asyncio.Lock()
        self.alerts = AlertStore()
        self.centroids = load_centroids()
        self.alerts_received = 0

    # ---------- 事件入口 ----------
    def ingest(self, evt: dict, recv_ms: int | None = None) -> None:
        if not isinstance(evt, dict):
            return
        recv = recv_ms or now_ms()
        src = evt.get("source")
        if src not in LAYERS:
            return
        self.consumed += 1
        self.rolling.add(src, recv // 1000)
        ingest_ms = int(evt.get("ingest_time_ms") or 0)
        if ingest_ms:
            self.lag.add(src, recv - ingest_ms)
        if src != "opensky" and evt.get("event_id"):
            self.minutes.add(src, evt["event_id"], int(evt.get("event_time_ms") or 0))
        self.last_event[src] = {
            "event_ms": int(evt.get("event_time_ms") or 0),
            "recv_ms": recv,
        }
        enc = encode(evt)
        if enc is None:
            return
        layer, key, row = enc
        if layer == "opensky":
            self.flights[key] = row[6]
        for c in self.clients:
            c.offer(layer, key, row)

    def flights_tracked(self, now: int | None = None) -> int:
        cutoff = (now or now_ms()) - self.s.flight_window_s * 1000
        for k in [k for k, t in self.flights.items() if t < cutoff]:
            del self.flights[k]
        return len(self.flights)

    def source_status(self, now: int) -> dict:
        out = {}
        for src in LAYERS:
            info = self.last_event.get(src)
            stale_ms = STALE_AFTER_MS.get(src, self.s.flight_window_s * 1000)
            if info is None:
                status = "waiting"
            elif now - info["recv_ms"] > stale_ms:
                status = "stale"
            else:
                status = "ok"
            out[src] = {"status": status, **(info or {})}
        return out

    def ingest_alert(self, raw: dict) -> dict | None:
        alert = normalize(raw, self.centroids)
        if alert is None:
            return None
        self.alerts_received += 1
        is_new = self.alerts.upsert(alert)
        msg = {"t": "alert", "alert": alert, "new": is_new}
        for c in self.clients:
            c.push_control(msg)
        return alert

    # ---------- 指标 ----------
    async def panel(self) -> dict:
        if self.ch is None:
            return {}
        # 单飞：缓存过期时，指标广播、/api/metrics、新连接可能同时到达，只让一个去查 ClickHouse
        async with self._panel_lock:
            if time.monotonic() - self._panel_at > self.s.ch_cache_s:
                try:
                    self._panel = await self.ch.panel()
                    self.ch_ok = True
                except Exception as exc:  # noqa: BLE001 指标查询失败不影响实时推送
                    self.ch_ok = False
                    log.warning("clickhouse panel query failed: %r", exc)
                self._panel_at = time.monotonic()
        return self._panel

    async def metrics(self) -> dict:
        now = now_ms()
        sec = now // 1000
        return {
            "t": "metrics",
            "server_ms": now,
            "eps": {src: self.rolling.rate(src, sec, 10) for src in LAYERS},
            "last_minute": {src: self.rolling.total(src, sec - 1, 60) for src in LAYERS},
            "lag_ms": {src: self.lag.quantiles(src) for src in LAYERS},
            "flights_tracked": self.flights_tracked(now),
            "sources": self.source_status(now),
            "clients": len(self.clients),
            "kafka_ok": self.kafka_ok,
            "clickhouse_ok": self.ch_ok,
            "alerts_1h": self.alerts.count_since(now - 3600_000),
            **(await self.panel()),
        }

    # ---------- 后台任务 ----------
    async def consume(self, source: Callable[[], AsyncIterator]) -> None:
        """source 产出 (topic, value) 元组；为兼容测试，也接受直接产出 evt.unified dict。"""
        async for item in source():
            if isinstance(item, tuple):
                topic, value = item
                if topic == "alert.anomaly":
                    self.ingest_alert(value)
                    continue
                self.ingest(value)
            else:
                self.ingest(item)

    async def broadcast_metrics(self) -> None:
        while True:
            await asyncio.sleep(self.s.metrics_interval_s)
            if not self.clients:
                continue
            m = await self.metrics()
            for c in list(self.clients):
                c.push_control(m)

    async def serve_client(self, session: ClientSession) -> None:
        await session.send_hello()
        self.clients.add(session)  # 先注册再查快照：快照期间到达的实时事件进缓冲区，不会漏
        try:
            await self._send_snapshots(session)
            session.push_control(await self.metrics())
            tasks = [
                asyncio.create_task(session.send_loop()),
                asyncio.create_task(session.recv_loop()),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        raise exc
            finally:
                for t in tasks:
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await t
        finally:
            self.clients.discard(session)

    async def _send_snapshots(self, session: ClientSession) -> None:
        if self.ch is None:
            return
        for layer in LAYERS:
            try:
                events = await self.ch.snapshot(layer, self.s.flight_window_s)
                self.ch_ok = True
            except Exception as exc:  # noqa: BLE001
                self.ch_ok = False
                log.warning("snapshot %s failed: %r", layer, exc)
                await session.send_raw(dumps({"t": "warn", "msg": f"snapshot {layer} unavailable"}))
                continue
            rows = [enc[2] for enc in map(encode, events) if enc is not None]
            await session.send_raw(dumps({"t": "snapshot", "layer": layer, "rows": rows}))
        await session.send_raw(dumps({"t": "alerts", "rows": await self._alert_snapshot()}))

    async def _alert_snapshot(self) -> list[dict]:
        """最近 6 小时告警：优先 ClickHouse（网关重启后也完整），失败则用内存里的。"""
        try:
            raw = await self.ch.recent_alerts(hours=6)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert snapshot failed: %r", exc)
            return self.alerts.recent()
        merged = {a["alert_id"]: a for a in (normalize(r, self.centroids) for r in raw) if a}
        for a in self.alerts.recent():
            merged[a["alert_id"]] = a  # 内存里的更新（还没落 ClickHouse 的修订）
        return sorted(merged.values(), key=lambda a: a["event_time_ms"], reverse=True)[:50]
