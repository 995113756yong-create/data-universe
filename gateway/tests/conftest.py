import json

import pytest

from gateway.config import GatewaySettings


def wiki_evt(i: int, t: int = 1_794_281_538_000, lat=39.8, lng=-98.6) -> dict:
    return {
        "event_id": f"w{i}",
        "source": "wiki",
        "event_type": "edit",
        "event_time_ms": t,
        "ingest_time_ms": t + 100,
        "version": t,
        "lat": lat,
        "lng": lng,
        "geo_precision": "approx",
        "region": "United States",
        "weight": 250.0,
        "title": f"Page {i}",
        "url": f"https://en.wikipedia.org/wiki/P{i}",
        "attrs": '{"wiki":"enwiki","lang":"en","bot":false,"namespace":0}',
    }


def flight_evt(icao: str, t: int, lat=45.0, lng=5.0) -> dict:
    return {
        "event_id": f"{icao}-{t // 1000}",
        "source": "opensky",
        "event_type": "flight_pos",
        "event_time_ms": t,
        "ingest_time_ms": t + 3000,
        "version": t,
        "lat": lat,
        "lng": lng,
        "geo_precision": "exact",
        "region": "France",
        "weight": 10675.62,
        "title": "AFR123",
        "url": "",
        "attrs": json.dumps(
            {
                "icao24": icao,
                "callsign": "AFR123",
                "velocity_ms": 225.78,
                "heading_deg": 208.14,
                "vertical_rate_ms": 0.33,
                "geo_altitude_m": 10873.74,
            }
        ),
    }


def alert_raw(
    aid="wiki_spike-Germany-2026-11-10 08:00:00",
    atype="wiki_spike",
    region="Germany",
    lat=None,
    lng=None,
    value=95.0,
    t=1_794_300_000_000,
):
    return {
        "alert_id": aid,
        "alert_type": atype,
        "source": "wiki" if atype == "wiki_spike" else "usgs",
        "region": region,
        "window_start": "2026-11-10 08:00:00",
        "event_time_ms": t,
        "detected_ms": t + 150_000,
        "value": value,
        "baseline_mean": 30.0 if atype == "wiki_spike" else None,
        "baseline_std": 6.123 if atype == "wiki_spike" else None,
        "zscore": 10.6 if atype == "wiki_spike" else None,
        "severity": "high",
        "lat": lat,
        "lng": lng,
        "title": "Wikipedia edit spike: Germany",
    }


class FakeWS:
    def __init__(self, send_delay: float = 0.0):
        self.sent: list[str] = []
        self.send_delay = send_delay

    async def send_text(self, data: str) -> None:
        import asyncio

        if self.send_delay:
            await asyncio.sleep(self.send_delay)
        self.sent.append(data)


class FakeCH:
    def __init__(self):
        self.closed = False

    async def snapshot(self, layer, flight_window_s):
        if layer == "wiki":
            return [wiki_evt(900 + i) for i in range(3)]
        if layer == "opensky":
            return [flight_evt("abc123", 1_794_281_538_000)]
        return []

    async def panel(self):
        return {
            "trend": [{"ts": 1, "source": "wiki", "cnt": 5}],
            "top_regions": [],
            "quakes_24h": {"count": 0, "max_mag": 0},
        }

    async def recent_alerts(self, hours=6):
        return [alert_raw("quake-us1", "quake_significant", region="Japan", lat=36.0, lng=140.0)]

    async def query(self, sql, settings=None):
        self.queries = getattr(self, "queries", []) + [sql]
        return {"columns": ["region", "cnt"], "rows": [["Germany", 120], ["Japan", 80]]}

    async def minute_counts(self, source):
        return {1_794_281_520_000: 2}

    async def close(self):
        self.closed = True


@pytest.fixture
def settings():
    return GatewaySettings(
        tick_ms=50,
        wiki_cap=50,
        wiki_cap_min=20,
        flight_cap=100,
        metrics_interval_s=0.2,
        static_dir="/nonexistent",
    )
