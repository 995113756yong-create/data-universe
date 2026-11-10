"""evt.unified 消息 -> 推送给浏览器的紧凑数组。字段顺序是前后端契约，见 docs/contracts.md。"""

from __future__ import annotations

import orjson

PROTOCOL_VERSION = 1

# 点图层（wiki / usgs）
POINT_FIELDS = ("id", "lat", "lng", "weight", "event_ms", "ingest_ms", "region", "title", "url")
# 航班图层
FLIGHT_FIELDS = (
    "icao24",
    "lat",
    "lng",
    "heading_deg",
    "velocity_ms",
    "altitude_m",
    "event_ms",
    "ingest_ms",
    "callsign",
    "origin_country",
)


def _attrs(evt: dict) -> dict:
    raw = evt.get("attrs")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = orjson.loads(raw)
        return val if isinstance(val, dict) else {}
    except orjson.JSONDecodeError:
        return {}


def _num(v):
    return None if v is None else round(float(v), 2)


def encode(evt: dict) -> tuple[str, str, list] | None:
    """返回 (layer, key, row)；无坐标或未知数据源返回 None。key 用于航班合并。"""
    if not isinstance(evt, dict):
        return None
    source = evt.get("source")
    lat, lng = evt.get("lat"), evt.get("lng")
    if lat is None or lng is None or not evt.get("event_id"):
        return None
    if source in ("wiki", "usgs"):
        row = [
            evt["event_id"],
            round(float(lat), 4),
            round(float(lng), 4),
            round(float(evt.get("weight") or 0.0), 2),
            int(evt.get("event_time_ms") or 0),
            int(evt.get("ingest_time_ms") or 0),
            evt.get("region") or "Unknown",
            (evt.get("title") or "")[:120],
            evt.get("url") or "",
        ]
        return source, evt["event_id"], row
    if source == "opensky":
        a = _attrs(evt)
        icao24 = a.get("icao24") or str(evt["event_id"]).split("-", 1)[0]
        row = [
            icao24,
            round(float(lat), 4),
            round(float(lng), 4),
            _num(a.get("heading_deg")),
            _num(a.get("velocity_ms")),
            round(float(evt.get("weight") or 0.0)),
            int(evt.get("event_time_ms") or 0),
            int(evt.get("ingest_time_ms") or 0),
            a.get("callsign") or evt.get("title") or "",
            evt.get("region") or "Unknown",
        ]
        return "opensky", icao24, row
    return None


def dumps(msg: dict) -> str:
    return orjson.dumps(msg).decode()
