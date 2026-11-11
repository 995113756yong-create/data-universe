import asyncio
import time

import orjson
from conftest import FakeCH, flight_evt, wiki_evt
from fastapi.testclient import TestClient

from gateway.app import create_app


def make_source(n=20, delay=0.4):
    async def source():
        await asyncio.sleep(delay)  # 等客户端连上
        for i in range(n):
            yield wiki_evt(i)
            await asyncio.sleep(0.005)
        yield flight_evt(
            "f1", time.time_ns() // 1_000_000
        )  # 必须是当前时间，否则超出 flight_window 被清理
        while True:
            await asyncio.sleep(1)

    return source


def test_ws_flow(settings):
    ch = FakeCH()
    app = create_app(settings, ch=ch, event_source=make_source())
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            hello = orjson.loads(ws.receive_text())
            assert hello["t"] == "hello" and hello["v"] == 1
            assert hello["layers"] == ["wiki", "usgs", "opensky"]
            snaps = [orjson.loads(ws.receive_text()) for _ in range(3)]
            assert [m["layer"] for m in snaps] == ["wiki", "usgs", "opensky"]
            assert len(snaps[0]["rows"]) == 3 and snaps[2]["rows"][0][0] == "abc123"

            got_wiki, got_flight, got_metrics = 0, 0, False
            for _ in range(200):
                m = orjson.loads(ws.receive_text())
                if m["t"] == "metrics":
                    got_metrics = True
                    assert "eps" in m and "trend" in m
                elif m["t"] == "batch":
                    got_wiki += len(m["rows"].get("wiki", []))
                    got_flight += len(m["rows"].get("opensky", []))
                if got_wiki >= 20 and got_flight >= 1 and got_metrics:
                    break
            assert got_wiki == 20 and got_flight == 1 and got_metrics

        r = client.get("/healthz").json()
        assert r["ok"] and r["kafka_ok"] and r["consumed"] == 21
        m = client.get("/api/metrics").json()
        assert m["flights_tracked"] == 1
        assert m["last_minute"]["wiki"] + m["eps"]["wiki"] >= 0
        mc = client.get("/api/debug/minute_counts?source=wiki").json()
        assert mc["gateway"] == {"1794281520000": 20}
        assert client.get("/api/debug/minute_counts?source=bad").status_code == 422
        assert client.get("/").status_code == 503  # 未构建前端时给出明确提示
    assert ch.closed


def test_ws_subscribe_only_flights(settings):
    app = create_app(settings, ch=FakeCH(), event_source=make_source(delay=0.6))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text('{"t":"subscribe","layers":["opensky"]}')
            for _ in range(4):
                ws.receive_text()  # hello + 3 snapshots
            flights = 0
            for _ in range(100):
                m = orjson.loads(ws.receive_text())
                if m["t"] == "batch":
                    assert "wiki" not in m["rows"]
                    flights += len(m["rows"].get("opensky", []))
                    if flights:
                        break
            assert flights == 1


class StubAgent:
    class llm:  # noqa: N801
        model = "stub"

    def __init__(self, fail=False):
        self.fail = fail
        self.questions = []

    async def ask(self, q):
        from gateway.ai.agent import AskError, AskResult

        self.questions.append(q)
        if self.fail:
            raise AskError("模型调用失败：HTTP 401")
        return AskResult(answer="ok", highlights=[{"lat": 1, "lng": 2, "label": "x"}], model="stub")


def _quiet_source():
    async def source():
        await asyncio.sleep(3600)
        yield {}

    return source


def test_ask_disabled(settings):
    app = create_app(settings, ch=FakeCH(), event_source=_quiet_source())
    with TestClient(app) as client:
        assert client.get("/api/ask/status").json()["enabled"] is False
        r = client.post("/api/ask", json={"question": "最近有地震吗"})
        assert r.status_code == 503


def test_ask_flow_validation_and_ratelimit(settings):
    from dataclasses import replace

    agent = StubAgent()
    app = create_app(
        replace(settings, ai_per_min=2), ch=FakeCH(), event_source=_quiet_source(), agent=agent
    )
    with TestClient(app) as client:
        assert client.get("/api/ask/status").json() == {
            "enabled": True,
            "provider": "deepseek",
            "model": "stub",
        }
        assert client.post("/api/ask", json={"question": "x"}).status_code == 422  # 太短
        assert client.post("/api/ask", json={"question": "a" * 301}).status_code == 422
        r = client.post("/api/ask", json={"question": "  最近有地震吗  "})
        assert r.status_code == 200 and r.json()["answer"] == "ok"
        assert agent.questions == ["最近有地震吗"]
        assert client.post("/api/ask", json={"question": "再问一次"}).status_code == 200
        r = client.post("/api/ask", json={"question": "第三次"})
        assert r.status_code == 429 and "频繁" in r.json()["error"]
        # 不同 IP（经反向代理）单独计数
        r = client.post(
            "/api/ask", json={"question": "第三次"}, headers={"x-forwarded-for": "9.9.9.9"}
        )
        assert r.status_code == 200


def test_ask_agent_error(settings):
    app = create_app(
        settings, ch=FakeCH(), event_source=_quiet_source(), agent=StubAgent(fail=True)
    )
    with TestClient(app) as client:
        r = client.post("/api/ask", json={"question": "最近有地震吗"})
        assert r.status_code == 502 and "401" in r.json()["error"]


def test_ws_sends_alert_snapshot(settings):
    app = create_app(settings, ch=FakeCH(), event_source=_quiet_source())
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        types = []
        for _ in range(6):
            m = ws.receive_json()
            types.append(m["t"])
            if m["t"] == "alerts":
                assert m["rows"][0]["alert_id"] == "quake-us1"
                break
        assert "alerts" in types
