import asyncio

import httpx
import orjson

from gateway.clickhouse import ClickHouse


def _run(coro):
    return asyncio.run(coro)


def _ch(handler):
    return ClickHouse("http://ch:8123", "du", "pw", transport=httpx.MockTransport(handler))


def test_readonly_params_and_auth_headers():
    seen = {}

    def handler(req: httpx.Request):
        seen["params"] = dict(req.url.params)
        seen["headers"] = req.headers
        seen["body"] = req.content.decode()
        return httpx.Response(200, content=orjson.dumps({"data": [[1, 2]]}))

    async def go():
        ch = _ch(handler)
        rows = await ch.rows("SELECT {x:UInt8}", x=5)
        await ch.close()
        return rows

    assert _run(go()) == [[1, 2]]
    assert seen["params"]["readonly"] == "2"
    assert seen["params"]["param_x"] == "5"
    assert seen["params"]["default_format"] == "JSONCompact"
    assert seen["headers"]["X-ClickHouse-User"] == "du"
    assert "password" not in str(seen["params"])  # 密码走 header，不进 URL/日志


def test_flight_snapshot_mapping():
    row = [
        "abc123",
        45.1,
        5.2,
        10000.0,
        1_794_281_538_000,
        1_794_281_541_000,
        "France",
        "AFR1",
        '{"icao24":"abc123","heading_deg":90}',
    ]

    def handler(req):
        assert "param_window_s" in req.url.params
        return httpx.Response(200, content=orjson.dumps({"data": [row]}))

    async def go():
        ch = _ch(handler)
        out = await ch.snapshot("opensky", 1200)
        await ch.close()
        return out

    evt = _run(go())[0]
    assert evt["event_id"] == "abc123-1794281538"
    assert evt["source"] == "opensky" and evt["lat"] == 45.1


def test_panel_shape():
    answers = iter(
        [
            {"data": [[1000, "wiki", "12"]]},
            {"data": [["wiki", "Germany", "7"]]},
            {"data": [["3", 5.4]]},
        ]
    )

    def handler(req):
        return httpx.Response(200, content=orjson.dumps(next(answers)))

    async def go():
        ch = _ch(handler)
        p = await ch.panel()
        await ch.close()
        return p

    p = _run(go())
    assert p["trend"] == [{"ts": 1000, "source": "wiki", "cnt": 12}]
    assert p["top_regions"][0]["cnt"] == 7
    assert p["quakes_24h"] == {"count": 3, "max_mag": 5.4}


def test_http_error_raises():
    async def go():
        ch = _ch(lambda req: httpx.Response(500, text="boom"))
        try:
            await ch.rows("SELECT 1")
        finally:
            await ch.close()

    try:
        _run(go())
    except httpx.HTTPStatusError:
        return
    raise AssertionError("expected HTTPStatusError")
