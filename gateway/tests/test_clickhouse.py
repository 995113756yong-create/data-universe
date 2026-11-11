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
            {"data": [["wiki_spike", "2"]]},
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
    assert p["alerts_24h"] == {"wiki_spike": 2}


def test_panel_tolerates_missing_alerts_table():
    answers = iter([{"data": []}, {"data": []}, {"data": [[0, 0]]}])

    def handler(req):
        try:
            return httpx.Response(200, content=orjson.dumps(next(answers)))
        except StopIteration:
            return httpx.Response(404, text="Table du.alerts doesn't exist")

    async def go():
        ch = _ch(handler)
        p = await ch.panel()
        await ch.close()
        return p

    assert _run(go())["alerts_24h"] == {}


def test_query_returns_columns_and_errors():
    from gateway.clickhouse import ClickHouseError

    def handler(req):
        if b"bad" in req.content:
            return httpx.Response(400, text="Code: 62. Syntax error")
        assert req.url.params["max_result_rows"] == "10"
        return httpx.Response(
            200, content=orjson.dumps({"meta": [{"name": "a", "type": "UInt8"}], "data": [[1]]})
        )

    async def go():
        ch = _ch(handler)
        ok = await ch.query("SELECT 1 AS a", {"max_result_rows": "10"})
        try:
            await ch.query("bad")
        except ClickHouseError as exc:
            err = str(exc)
        await ch.close()
        return ok, err

    ok, err = _run(go())
    assert ok == {"columns": ["a"], "rows": [[1]]}
    assert "Syntax error" in err


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


def test_minute_counts_lower_bound_is_minute_aligned():
    """回归：下界用 now-15min 会把最早一分钟截成半分钟，网关/ClickHouse 比值偏高（实测 1.059）。"""
    from gateway.clickhouse import MINUTE_COUNTS

    assert "toStartOfMinute(now64(3) - INTERVAL 15 MINUTE)" in MINUTE_COUNTS


def test_panel_tolerates_alerts_timeout():
    """回归：告警计数查询超时不能拖垮整个面板（否则 clickhouse_ok 变 False）。"""

    answers = iter([{"data": []}, {"data": []}, {"data": [[0, 0]]}])  # trend / top / quakes

    def handler(req):
        if b"du.alerts" in req.content:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, content=orjson.dumps(next(answers)))

    async def go():
        ch = _ch(handler)
        try:
            return await ch.panel()
        finally:
            await ch.close()

    assert _run(go())["alerts_24h"] == {}
