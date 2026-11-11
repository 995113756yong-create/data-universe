"""OpenAI 兼容 Chat Completions 客户端。

适用 DeepSeek / 通义千问 / Kimi / OpenAI / 本地 Ollama 等；只用 httpx，不依赖 openai SDK。
"""

from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("gateway.llm")


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_s, connect=5.0),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """返回 choices[0].message（含 content / tool_calls）。429/5xx 重试 2 次。"""
        body: dict = {"model": self.model, "messages": messages, "temperature": 0.1}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last = ""
        for attempt in range(3):
            try:
                resp = await self._client.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last = repr(exc)
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    try:
                        return data["choices"][0]["message"]
                    except (KeyError, IndexError, TypeError) as exc:
                        raise LLMError(f"响应格式异常：{str(data)[:200]}") from exc
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code not in (429, 500, 502, 503, 504):
                    raise LLMError(last)
            await asyncio.sleep(0.5 * (2**attempt))
        raise LLMError(last)
