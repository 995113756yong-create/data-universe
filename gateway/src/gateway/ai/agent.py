"""提问编排：模型 -> run_sql（守卫 + 只读账号）-> 模型 -> final_answer。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import orjson

from gateway.ai.llm import LLMClient, LLMError
from gateway.ai.prompt import TOOLS, system_prompt
from gateway.ai.sqlguard import GuardError, check_sql

log = logging.getLogger("gateway.ai")

MAX_STEPS = 6  # 模型调用次数上限
MAX_SQL = 4  # run_sql 次数上限
ROWS_TO_MODEL = 50  # 回给模型的行数（控制 token）
ROWS_TO_CLIENT = 20
CH_SETTINGS = {
    "max_execution_time": "8",
    "max_result_rows": "200",
    "result_overflow_mode": "break",
    "max_rows_to_read": "200000000",
}


class AskError(Exception):
    def __init__(self, msg: str, status: int = 502) -> None:
        super().__init__(msg)
        self.status = status


@dataclass
class AskResult:
    answer: str
    highlights: list[dict] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    table: dict | None = None
    steps: int = 0
    elapsed_ms: int = 0
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "highlights": self.highlights,
            "sql": self.sql,
            "table": self.table,
            "steps": self.steps,
            "elapsed_ms": self.elapsed_ms,
            "model": self.model,
        }


def _json_safe(v):
    if isinstance(v, float) and v != v:  # NaN
        return None
    return v


def resolve_highlights(raw, centroids: dict[str, tuple[float, float]]) -> list[dict]:
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    lower = {k.lower(): k for k in centroids}
    for h in raw[:10]:
        if not isinstance(h, dict):
            continue
        label = str(h.get("label") or h.get("region") or "")[:40]
        lat, lng = h.get("lat"), h.get("lng")
        precision = "exact"
        try:
            lat, lng = float(lat), float(lng)
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
        except (TypeError, ValueError):
            name = lower.get(str(h.get("region") or "").strip().lower())
            if name is None:
                continue
            lat, lng = centroids[name]
            precision = "approx"
        key = (round(lat, 2), round(lng, 2))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {"lat": round(lat, 4), "lng": round(lng, 4), "label": label, "geo_precision": precision}
        )
    return out


class Agent:
    def __init__(self, llm: LLMClient, ch, centroids: dict[str, tuple[float, float]]) -> None:
        self.llm = llm
        self.ch = ch
        self.centroids = centroids

    async def _run_sql(self, sql: str, result: AskResult) -> str:
        """返回给模型的工具结果（JSON 字符串）。"""
        try:
            safe = check_sql(sql)
        except GuardError as exc:
            return orjson.dumps({"error": f"SQL 被拒绝：{exc}"}).decode()
        result.sql.append(safe)
        try:
            data = await self.ch.query(safe, CH_SETTINGS)
        except Exception as exc:  # noqa: BLE001  ClickHouse 报错交给模型改写
            return orjson.dumps({"error": f"执行失败：{str(exc)[:400]}"}).decode()
        rows = [[_json_safe(v) for v in r] for r in data["rows"]]
        result.table = {
            "columns": data["columns"],
            "rows": rows[:ROWS_TO_CLIENT],
            "total": len(rows),
        }
        return orjson.dumps(
            {"columns": data["columns"], "rows": rows[:ROWS_TO_MODEL], "row_count": len(rows)}
        ).decode()

    async def ask(self, question: str) -> AskResult:
        t0 = time.monotonic()
        result = AskResult(answer="", model=self.llm.model)
        messages: list[dict] = [
            {"role": "system", "content": system_prompt(MAX_SQL)},
            {"role": "user", "content": question},
        ]
        sql_calls = 0
        for step in range(1, MAX_STEPS + 1):
            result.steps = step
            tools = TOOLS if sql_calls < MAX_SQL else [TOOLS[1]]
            try:
                msg = await self.llm.chat(messages, tools)
            except LLMError as exc:
                raise AskError(f"模型调用失败：{exc}") from exc
            calls = msg.get("tool_calls") or []
            if not calls:
                # 部分模型不调工具直接回答：接受文字作为最终答案
                result.answer = (msg.get("content") or "").strip()[:600] or "没有得到回答"
                break
            messages.append(
                {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}
            )
            final = None
            for call in calls:
                fn = call.get("function") or {}
                try:
                    args = orjson.loads(fn.get("arguments") or "{}")
                except orjson.JSONDecodeError:
                    args = {}
                if fn.get("name") == "final_answer":
                    final = args
                    content = "ok"
                elif fn.get("name") == "run_sql" and sql_calls < MAX_SQL:
                    sql_calls += 1
                    content = await self._run_sql(str(args.get("sql") or ""), result)
                else:
                    content = orjson.dumps({"error": "未知工具或超过查询次数"}).decode()
                messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": content}
                )
            if final is not None:
                result.answer = str(final.get("answer") or "").strip()[:600]
                result.highlights = resolve_highlights(final.get("highlights"), self.centroids)
                break
        else:
            result.answer = result.answer or "查询步骤过多，没能得出结论，请换个更具体的问法。"
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "ask q=%r steps=%d sql=%d ms=%d",
            question[:80],
            result.steps,
            len(result.sql),
            result.elapsed_ms,
        )
        return result
