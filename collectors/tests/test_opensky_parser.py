import json
from pathlib import Path

import httpx
import pytest

from collectors.opensky.auth import TokenProvider
from collectors.opensky.parser import RAW_OPENSKY_FIELDS, parse_response, parse_state
from collectors.opensky.poller import retry_after_seconds

FIXTURE = Path(__file__).parent / "fixtures" / "opensky_states.json"
INGEST = 1794281540000


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text())


def test_contract_fields_exact(payload):
    rec = parse_state(payload["states"][0], payload["time"], INGEST)
    assert tuple(rec.keys()) == RAW_OPENSKY_FIELDS


def test_real_sample_parsed(payload):
    rec = parse_state(payload["states"][0], payload["time"], INGEST)
    assert rec["icao24"] == "a3a67b"
    assert rec["callsign"] == "UPS242"  # 去掉补齐空格
    assert rec["origin_country"] == "United States"
    assert rec["lng"] == 5.4216 and rec["lat"] == 45.4219  # 下标 5 是经度，6 是纬度
    assert rec["baro_altitude_m"] == 10675.62
    assert rec["heading_deg"] == 208.14
    assert rec["event_time_ms"] == 1794281538 * 1000
    assert rec["event_id"] == "a3a67b-1794281538"


def test_filter_rules(payload):
    records, filtered = parse_response(payload, INGEST)
    ids = [r["icao24"] for r in records]
    assert len(ids) == 7  # 6 条真实 + abc005
    assert "abc005" in ids
    for dropped in ("abc001", "abc002", "abc003", "abc004"):
        assert dropped not in ids
    assert filtered == 4


def test_nullable_fields(payload):
    rec = next(r for r in parse_response(payload, INGEST)[0] if r["icao24"] == "abc005")
    assert rec["callsign"] == ""
    assert rec["baro_altitude_m"] is None and rec["velocity_ms"] is None
    assert rec["geo_altitude_m"] == 8000.0


@pytest.mark.parametrize("bad", [None, [], ["x"] * 5, {"a": 1}])
def test_bad_state(bad):
    assert parse_state(bad, 0, INGEST) is None


def test_empty_states():
    assert parse_response({"time": 1, "states": None}, INGEST) == ([], 0)


def test_retry_after_header():
    r = httpx.Response(429, headers={"X-Rate-Limit-Retry-After-Seconds": "321"})
    assert retry_after_seconds(r, 10) == 321
    assert retry_after_seconds(httpx.Response(429), 10) == 10
    assert (
        retry_after_seconds(
            httpx.Response(429, headers={"X-Rate-Limit-Retry-After-Seconds": "x"}), 10
        )
        == 10
    )


def test_token_refresh_margin():
    now = [0.0]
    tp = TokenProvider("id", "secret", clock=lambda: now[0])
    assert tp.needs_refresh()
    tp._token, tp._expires_at = "t", 1800.0
    now[0] = 1700.0
    assert not tp.needs_refresh()
    now[0] = 1741.0
    assert tp.needs_refresh()  # 到期前 60 秒刷新


async def _token_flow():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content.decode())
        return httpx.Response(200, json={"access_token": "abc", "expires_in": 1800})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tp = TokenProvider("id", "secret")
        assert await tp.get(client) == "abc"
        assert await tp.get(client) == "abc"
    return calls


def test_token_cached():
    import asyncio

    calls = asyncio.run(_token_flow())
    assert len(calls) == 1
    assert "grant_type=client_credentials" in calls[0]
