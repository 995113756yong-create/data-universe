"""ClickHouse 只读查询：首屏快照与面板指标。

浏览器不直连 ClickHouse：一是不能把账号密码暴露给前端，二是 ClickHouse HTTP 接口不返回 CORS 头。
"""

from __future__ import annotations

import httpx
import orjson

SNAPSHOT_WIKI = """
SELECT event_id, lat, lng, weight, toUnixTimestamp64Milli(event_time),
       toUnixTimestamp64Milli(ingest_time), region, title, url
FROM du.events
WHERE source = 'wiki' AND event_time > now64(3) - INTERVAL 120 SECOND AND lat IS NOT NULL
ORDER BY event_time DESC
LIMIT 3000
"""

SNAPSHOT_USGS = """
SELECT event_id, lat, lng, weight, toUnixTimestamp64Milli(event_time),
       toUnixTimestamp64Milli(ingest_time), region, title, url
FROM du.events FINAL
WHERE source = 'usgs' AND event_time > now64(3) - INTERVAL 24 HOUR
ORDER BY event_time DESC
LIMIT 2000
"""

SNAPSHOT_FLIGHTS = """
SELECT splitByChar('-', event_id)[1] AS icao24,
       argMax(lat, event_time), argMax(lng, event_time), argMax(weight, event_time),
       max(toUnixTimestamp64Milli(event_time)),
       argMax(toUnixTimestamp64Milli(ingest_time), event_time),
       argMax(region, event_time), argMax(title, event_time), argMax(attrs, event_time)
FROM du.events
WHERE source = 'opensky' AND event_time > now64(3) - INTERVAL {window_s:UInt32} SECOND
GROUP BY icao24
LIMIT 20000
"""

TREND_30M = """
SELECT toUnixTimestamp(window_start) * 1000 AS ts, source, sum(event_cnt) AS cnt
FROM du.agg_minute FINAL
WHERE window_start >= now() - INTERVAL 30 MINUTE
GROUP BY ts, source
ORDER BY ts
"""

TOP_REGIONS_10M = """
SELECT source, region, sum(event_cnt) AS cnt
FROM du.agg_minute FINAL
WHERE window_start >= now() - INTERVAL 10 MINUTE AND region != 'Unknown'
GROUP BY source, region
ORDER BY cnt DESC
LIMIT 10
"""

QUAKES_24H = """
SELECT count(), max(weight)
FROM du.events FINAL
WHERE source = 'usgs' AND event_time > now64(3) - INTERVAL 24 HOUR
"""

MINUTE_COUNTS = """
SELECT toUnixTimestamp(toStartOfMinute(event_time)) * 1000 AS m, uniqExact(event_id)
FROM du.events
WHERE source = {source:String} AND event_time >= now64(3) - INTERVAL 15 MINUTE
GROUP BY m
ORDER BY m
"""

RECENT_ALERTS = """
SELECT alert_id, alert_type, source, region, window_start,
       toUnixTimestamp64Milli(event_time), toUnixTimestamp64Milli(detected_time),
       value, baseline_mean, baseline_std, zscore, severity, lat, lng, title
FROM du.alerts FINAL
WHERE event_time > now64(3) - INTERVAL {hours:UInt32} HOUR
ORDER BY event_time DESC
LIMIT 100
"""

ALERTS_24H = """
SELECT alert_type, count()
FROM du.alerts FINAL
WHERE event_time > now64(3) - INTERVAL 24 HOUR
GROUP BY alert_type
"""

POINT_KEYS = (
    "event_id",
    "lat",
    "lng",
    "weight",
    "event_time_ms",
    "ingest_time_ms",
    "region",
    "title",
    "url",
)


class ClickHouseError(Exception):
    """ClickHouse 返回 4xx/5xx，消息为服务端错误文本（截断）。"""


class ClickHouse:
    def __init__(
        self, url: str, user: str, password: str, transport=None, timeout_s: float = 8.0
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=url,
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
            headers={"X-ClickHouse-User": user, "X-ClickHouse-Key": password},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def rows(self, sql: str, **params) -> list[list]:
        query = {
            "database": "du",
            "readonly": "2",  # 只读；=2 才允许同时在 URL 上设置 max_execution_time
            "max_execution_time": "5",
            "default_format": "JSONCompact",
        }
        for k, v in params.items():
            query[f"param_{k}"] = str(v)
        resp = await self._client.post("/", params=query, content=sql.encode())
        resp.raise_for_status()
        return orjson.loads(resp.content)["data"]

    async def query(self, sql: str, settings: dict[str, str] | None = None) -> dict:
        """执行任意（已校验的）只读 SQL，返回 {columns, rows}。

        供 AI 提问使用，必须用只读账号 du_ai 建的实例调用（账号级 readonly=2，见迁移 004）。
        """
        query = {
            "database": "du",
            "default_format": "JSONCompact",
            **(settings or {}),
        }
        resp = await self._client.post("/", params=query, content=sql.encode())
        if resp.status_code >= 400:
            raise ClickHouseError(resp.text[:800])
        body = orjson.loads(resp.content)
        return {"columns": [m["name"] for m in body.get("meta", [])], "rows": body.get("data", [])}

    async def recent_alerts(self, hours: int = 6) -> list[dict]:
        from gateway.alerts import ALERT_FIELDS

        rows = await self.rows(RECENT_ALERTS, hours=hours)
        return [dict(zip(ALERT_FIELDS, r, strict=True)) for r in rows]

    async def snapshot(self, layer: str, flight_window_s: int) -> list[dict]:
        """返回 evt.unified 形态的 dict，与实时消息统一走 protocol.encode。"""
        if layer == "opensky":
            out = []
            for r in await self.rows(SNAPSHOT_FLIGHTS, window_s=flight_window_s):
                out.append(
                    {
                        "event_id": f"{r[0]}-{int(r[4]) // 1000}",
                        "source": "opensky",
                        "lat": r[1],
                        "lng": r[2],
                        "weight": r[3],
                        "event_time_ms": int(r[4]),
                        "ingest_time_ms": int(r[5]),
                        "region": r[6],
                        "title": r[7],
                        "attrs": r[8],
                    }
                )
            return out
        sql = SNAPSHOT_WIKI if layer == "wiki" else SNAPSHOT_USGS
        return [dict(zip(POINT_KEYS, r, strict=True), source=layer) for r in await self.rows(sql)]

    async def panel(self) -> dict:
        trend = await self.rows(TREND_30M)
        top = await self.rows(TOP_REGIONS_10M)
        quakes = await self.rows(QUAKES_24H)
        try:
            alerts = {t: int(c) for t, c in await self.rows(ALERTS_24H)}
        except httpx.HTTPStatusError:
            alerts = {}  # 迁移 003 未执行时 du.alerts 不存在，不影响其他面板数据
        q_cnt, q_max = quakes[0] if quakes else (0, 0)
        return {
            "trend": [{"ts": int(t), "source": s, "cnt": int(c)} for t, s, c in trend],
            "top_regions": [{"source": s, "region": r, "cnt": int(c)} for s, r, c in top],
            "quakes_24h": {"count": int(q_cnt), "max_mag": float(q_max or 0)},
            "alerts_24h": alerts,
        }

    async def minute_counts(self, source: str) -> dict[int, int]:
        return {int(m): int(c) for m, c in await self.rows(MINUTE_COUNTS, source=source)}
