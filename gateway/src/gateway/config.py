from __future__ import annotations

import os
from dataclasses import dataclass

LAYERS = ("wiki", "usgs", "opensky")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class GatewaySettings:
    kafka_bootstrap: str = "redpanda:9092"
    clickhouse_url: str = "http://clickhouse:8123"
    clickhouse_user: str = "du"
    clickhouse_password: str = "du_dev"
    static_dir: str = "/app/static"
    host: str = "0.0.0.0"
    port: int = 8090
    tick_ms: int = 200
    wiki_cap: int = 200  # 每个 tick、每个客户端最多推送的维基点数（即 1000 点/秒）
    wiki_cap_min: int = 20
    flight_cap: int = 2500  # 每个 tick 最多推送的航班更新数，其余留到下个 tick
    flight_window_s: int = 1200  # 超过该时间没有新位置的飞机视为离开
    metrics_interval_s: float = 2.0
    ch_cache_s: float = 10.0
    max_clients: int = 50

    @classmethod
    def from_env(cls) -> GatewaySettings:
        d = cls()
        s = cls(
            kafka_bootstrap=os.getenv("KAFKA_BOOTSTRAP", d.kafka_bootstrap),
            clickhouse_url=os.getenv("CLICKHOUSE_URL", d.clickhouse_url),
            clickhouse_user=os.getenv("CLICKHOUSE_USER", d.clickhouse_user),
            clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", d.clickhouse_password),
            static_dir=os.getenv("STATIC_DIR", d.static_dir),
            port=_int("GATEWAY_PORT", d.port),
            tick_ms=_int("TICK_MS", d.tick_ms),
            wiki_cap=_int("WIKI_CAP", d.wiki_cap),
            flight_cap=_int("FLIGHT_CAP", d.flight_cap),
            flight_window_s=_int("FLIGHT_WINDOW_S", d.flight_window_s),
        )
        if not 50 <= s.tick_ms <= 1000:
            raise ValueError("TICK_MS 必须在 50~1000 之间")
        if s.wiki_cap < s.wiki_cap_min or s.flight_cap < 100:
            raise ValueError("WIKI_CAP / FLIGHT_CAP 过小")
        return s
