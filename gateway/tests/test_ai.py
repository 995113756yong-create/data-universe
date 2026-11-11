import asyncio

import httpx
import orjson
import pytest

from gateway.ai.agent import Agent, AskError, resolve_highlights
from gateway.ai.llm import LLMClient, LLMError
from gateway.ai.ratelimit import RateLimiter
from gateway.alerts import load_centroids

CENT = load_centroids()


def _call(name, args, cid="c1"):
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": orjson.dumps(args).decode()},
    }


class ScriptedLLM:
    """按顺序返回预设的 assistant message，并记录收到的 messages。"""

    model = "fake-model"

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    async def chat(self, messages, tools=None):
        self.seen.append((list(messages), [t["function"]["name"] for t in tools or []]))
        if not self.script:
            raise LLMError("script exhausted")
        return self.script.pop(0)


class FakeAICH:
    def __init__(self, fail=None):
        self.fail = fail
        self.sql = []

    async def query(self, sql, settings=None):
        self.sql.append(sql)
        assert settings["max_execution_time"] == "8"
        if self.fail:
            raise RuntimeError(self.fail)
        return {"columns": ["region", "c"], "rows": [["Germany", 120], ["Japan", 80]]}


def run(coro):
    return asyncio.run(coro)


def test_happy_path_sql_then_answer():
    llm = ScriptedLLM(
        [
            {
                "content": "",
                "tool_calls": [
                    _call(
                        "run_sql",
                        {"sql": "SELECT region, count() c FROM du.events GROUP BY region"},
                    )
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    _call(
                        "final_answer",
                        {
                            "answer": "德国最多，120 次。",
                            "highlights": [
                                {"label": "Germany 120", "region": "germany"},
                                {"label": "Tokyo", "lat": 35.6, "lng": 139.7},
                            ],
                        },
                        "c2",
                    )
                ],
            },
        ]
    )
    ch = FakeAICH()
    res = run(Agent(llm, ch, CENT).ask("哪个地区编辑最多"))
    assert res.answer == "德国最多，120 次。"
    assert res.steps == 2
    assert "LIMIT 200" in res.sql[0] and ch.sql == res.sql
    assert res.table["rows"][0] == ["Germany", 120]
    assert res.highlights[0]["geo_precision"] == "approx"
    assert (res.highlights[0]["lat"], res.highlights[0]["lng"]) == CENT["Germany"]
    assert res.highlights[1]["geo_precision"] == "exact"
    # 工具结果以 tool 消息回给模型
    second_msgs = llm.seen[1][0]
    assert second_msgs[-1]["role"] == "tool" and "Germany" in second_msgs[-1]["content"]


def test_guard_rejection_goes_back_to_model():
    llm = ScriptedLLM(
        [
            {"tool_calls": [_call("run_sql", {"sql": "SELECT * FROM system.users"})]},
            {"tool_calls": [_call("final_answer", {"answer": "无法查询"}, "c2")]},
        ]
    )
    ch = FakeAICH()
    res = run(Agent(llm, ch, CENT).ask("看看用户表"))
    assert ch.sql == [] and res.sql == []
    assert "SQL 被拒绝" in llm.seen[1][0][-1]["content"]


def test_clickhouse_error_goes_back_to_model():
    llm = ScriptedLLM(
        [
            {"tool_calls": [_call("run_sql", {"sql": "SELECT nope FROM du.events"})]},
            {"tool_calls": [_call("final_answer", {"answer": "x"}, "c2")]},
        ]
    )
    run(Agent(llm, FakeAICH(fail="Code: 47. Unknown identifier nope"), CENT).ask("q"))
    assert "Unknown identifier" in llm.seen[1][0][-1]["content"]


def test_sql_budget_then_only_final_tool():
    q = {"tool_calls": [_call("run_sql", {"sql": "SELECT 1"})]}
    llm = ScriptedLLM([q, q, q, q, {"tool_calls": [_call("final_answer", {"answer": "done"})]}])
    res = run(Agent(llm, FakeAICH(), CENT).ask("q"))
    assert len(res.sql) == 4
    assert llm.seen[4][1] == ["final_answer"]
    assert res.answer == "done"


def test_max_steps():
    q = {"tool_calls": [_call("bogus", {})]}
    llm = ScriptedLLM([q] * 6)
    res = run(Agent(llm, FakeAICH(), CENT).ask("q"))
    assert "步骤过多" in res.answer and res.steps == 6


def test_plain_text_answer_accepted():
    res = run(
        Agent(ScriptedLLM([{"content": "只能回答实时数据相关问题"}]), FakeAICH(), CENT).ask("你好")
    )
    assert res.answer == "只能回答实时数据相关问题" and res.highlights == []


def test_llm_failure_raises():
    with pytest.raises(AskError):
        run(Agent(ScriptedLLM([]), FakeAICH(), CENT).ask("q"))


def test_resolve_highlights_filters():
    out = resolve_highlights(
        [
            {"label": "bad", "lat": 999, "lng": 0},
            {"label": "x", "region": "Nowhere"},
            "junk",
            {"label": "a", "lat": 10, "lng": 20},
            {"label": "dup", "lat": 10.001, "lng": 20.001},
        ],
        CENT,
    )
    assert [h["label"] for h in out] == ["a"]
    assert resolve_highlights(None, CENT) == []


def test_llm_client_retries_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        body = orjson.loads(req.content)
        assert req.headers["authorization"] == "Bearer k"
        assert body["model"] == "m" and body["tools"][0]["function"]["name"] == "t"
        if calls["n"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async def go():
        c = LLMClient("https://x/v1/", "k", "m", transport=httpx.MockTransport(handler))
        try:
            return await c.chat(
                [{"role": "user", "content": "q"}],
                [{"type": "function", "function": {"name": "t"}}],
            )
        finally:
            await c.close()

    assert run(go()) == {"content": "hi"} and calls["n"] == 2


def test_llm_client_no_retry_on_401():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    async def go():
        c = LLMClient("https://x/v1", "k", "m", transport=httpx.MockTransport(handler))
        try:
            await c.chat([])
        finally:
            await c.close()

    with pytest.raises(LLMError, match="401"):
        run(go())
    assert calls["n"] == 1


def test_rate_limiter():
    t = [1_800_000_000.0]
    rl = RateLimiter(per_min=2, per_day=3, clock=lambda: t[0])
    assert rl.check("a") is None and rl.check("a") is None
    assert "频繁" in rl.check("a")
    t[0] += 61
    assert rl.check("a") is None
    assert "今日" in rl.check("b")
    t[0] += 86400
    assert rl.check("b") is None


def test_settings_presets(monkeypatch):
    from gateway.config import GatewaySettings

    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "k")
    s = GatewaySettings.from_env()
    assert s.ai_enabled and s.llm_base_url == "https://api.moonshot.cn/v1"
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    with pytest.raises(ValueError):
        GatewaySettings.from_env()
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen2.5")
    assert GatewaySettings.from_env().llm_model == "qwen2.5"
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.delenv("LLM_BASE_URL")
    assert not GatewaySettings.from_env().ai_enabled  # 未开启时不校验
