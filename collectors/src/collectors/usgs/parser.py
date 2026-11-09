"""USGS GeoJSON feature -> raw.usgs 消息。纯函数，不做 IO。契约见 docs/contracts.md。"""

from __future__ import annotations

from typing import Any

RAW_USGS_FIELDS = (
    "event_id",
    "quake_type",
    "mag",
    "place",
    "region",
    "lat",
    "lng",
    "depth_km",
    "event_time_ms",
    "updated_ms",
    "ingest_time_ms",
    "url",
    "title",
)

US_STATE_NAMES = frozenset(
    """Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia
    Hawaii Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts
    Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada Ohio Oklahoma Oregon
    Pennsylvania Tennessee Texas Utah Vermont Virginia Washington Wisconsin Wyoming""".split()
) | frozenset(
    {
        "New Hampshire",
        "New Jersey",
        "New Mexico",
        "New York",
        "North Carolina",
        "North Dakota",
        "Rhode Island",
        "South Carolina",
        "South Dakota",
        "West Virginia",
    }
)

US_STATE_CODES = frozenset(
    """AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ
    NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split()
)

REGION_ALIASES = {"MX": "Mexico"}


def derive_region(place: str | None) -> str:
    """place 取最后一个 ", " 之后的部分；美国州名/州代码统一为 United States。"""
    if not place or not place.strip():
        return "Unknown"
    tail = place.rsplit(", ", 1)[-1].strip()
    if not tail:
        return "Unknown"
    if tail in US_STATE_CODES or tail in US_STATE_NAMES:
        return "United States"
    return REGION_ALIASES.get(tail, tail)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_feature(feature: dict, ingest_time_ms: int) -> dict | None:
    """无法解析（缺 id / 缺坐标 / 缺时间）返回 None。"""
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    event_id = feature.get("id")
    event_time = props.get("time")

    if not event_id or event_time is None or len(coords) < 2:
        return None
    lng, lat = _to_float(coords[0]), _to_float(coords[1])
    if lat is None or lng is None:
        return None

    try:
        event_time_ms = int(event_time)
        updated = props.get("updated")
        updated_ms = int(updated) if updated is not None else event_time_ms
    except (TypeError, ValueError):
        return None

    return {
        "event_id": str(event_id),
        "quake_type": props.get("type") or "earthquake",
        "mag": _to_float(props.get("mag")),
        "place": props.get("place"),
        "region": derive_region(props.get("place")),
        "lat": lat,
        "lng": lng,
        "depth_km": _to_float(coords[2]) if len(coords) > 2 else None,
        "event_time_ms": event_time_ms,
        "updated_ms": updated_ms,
        "ingest_time_ms": int(ingest_time_ms),
        "url": props.get("url") or "",
        "title": props.get("title") or "",
    }
