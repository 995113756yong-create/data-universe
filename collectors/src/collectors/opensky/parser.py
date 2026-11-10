"""OpenSky /states/all 返回 -> raw.opensky 消息。纯函数，不做 IO。契约见 docs/contracts.md。

state vector 下标（官方文档）：
 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact, 5 longitude, 6 latitude,
 7 baro_altitude, 8 on_ground, 9 velocity, 10 true_track, 11 vertical_rate, 12 sensors,
 13 geo_altitude, 14 squawk, 15 spi, 16 position_source
"""

from __future__ import annotations

from typing import Any

RAW_OPENSKY_FIELDS = (
    "event_id",
    "icao24",
    "callsign",
    "origin_country",
    "lat",
    "lng",
    "baro_altitude_m",
    "geo_altitude_m",
    "velocity_ms",
    "heading_deg",
    "vertical_rate_ms",
    "event_time_ms",
    "last_contact_ms",
    "ingest_time_ms",
)

# 位置报告比响应时间早超过该值视为过期（飞机已失联），不展示
MAX_POSITION_AGE_S = 60


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_state(state: list, response_time_s: int, ingest_time_ms: int) -> dict | None:
    """过滤：字段不足 / 无 icao24 / 无 time_position / 无坐标 / 在地面 / 位置过期 -> None。"""
    if not isinstance(state, (list, tuple)) or len(state) < 14:
        return None
    icao24 = state[0]
    time_position = state[3]
    lng, lat = _f(state[5]), _f(state[6])
    if not icao24 or time_position is None or lat is None or lng is None:
        return None
    if state[8] is True:
        return None
    try:
        tp = int(time_position)
        last_contact = int(state[4]) if state[4] is not None else tp
    except (TypeError, ValueError):
        return None
    if response_time_s - tp > MAX_POSITION_AGE_S:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    icao24 = str(icao24).strip().lower()
    return {
        "event_id": f"{icao24}-{tp}",
        "icao24": icao24,
        "callsign": (state[1] or "").strip(),
        "origin_country": state[2] or "Unknown",
        "lat": lat,
        "lng": lng,
        "baro_altitude_m": _f(state[7]),
        "geo_altitude_m": _f(state[13]),
        "velocity_ms": _f(state[9]),
        "heading_deg": _f(state[10]),
        "vertical_rate_ms": _f(state[11]),
        "event_time_ms": tp * 1000,
        "last_contact_ms": last_contact * 1000,
        "ingest_time_ms": int(ingest_time_ms),
    }


def parse_response(payload: dict, ingest_time_ms: int) -> tuple[list[dict], int]:
    """返回 (有效记录, 被过滤条数)。"""
    states = payload.get("states") or []
    resp_time = int(payload.get("time") or ingest_time_ms // 1000)
    out: list[dict] = []
    for st in states:
        rec = parse_state(st, resp_time, ingest_time_ms)
        if rec is not None:
            out.append(rec)
    return out, len(states) - len(out)
