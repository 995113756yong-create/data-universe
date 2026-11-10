from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gateway.ai.ratelimit import RateLimiter
from gateway.clickhouse import ClickHouse
from gateway.config import GatewaySettings
from gateway.hub import Hub
from gateway.session import ClientSession

log = logging.getLogger("gateway.app")


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=300)


def _client_key(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(
    settings: GatewaySettings | None = None,
    ch: ClickHouse | None = None,
    event_source: Callable[[], AsyncIterator[dict]] | None = None,
    agent=None,
) -> FastAPI:
    settings = settings or GatewaySettings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal ch
        if ch is None:
            ch = ClickHouse(
                settings.clickhouse_url, settings.clickhouse_user, settings.clickhouse_password
            )
        hub = Hub(settings, ch)
        app.state.hub = hub
        if event_source is None:
            from gateway.kafka_source import kafka_source

            source = kafka_source(settings.kafka_bootstrap, hub)
        else:
            hub.kafka_ok = True
            source = event_source
        app.state.agent = agent
        closers = []
        if agent is None and settings.ai_enabled:
            from gateway.ai.agent import Agent
            from gateway.ai.llm import LLMClient

            llm = LLMClient(
                settings.llm_base_url,
                settings.llm_api_key,
                settings.llm_model,
                settings.llm_timeout_s,
            )
            ai_ch = ClickHouse(
                settings.clickhouse_url,
                settings.ai_ch_user,
                settings.ai_ch_password,
                timeout_s=15.0,
            )
            app.state.agent = Agent(llm, ai_ch, hub.centroids)
            closers += [llm.close, ai_ch.close]
            log.info("AI enabled: provider=%s model=%s", settings.llm_provider, settings.llm_model)
        app.state.ai_sem = asyncio.Semaphore(settings.ai_concurrency)
        app.state.limiter = RateLimiter(settings.ai_per_min, settings.ai_per_day)
        tasks = [
            asyncio.create_task(hub.consume(source), name="consume"),
            asyncio.create_task(hub.broadcast_metrics(), name="metrics"),
        ]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            await ch.close()
            for close in closers:
                await close()

    app = FastAPI(title="Data Universe Gateway", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        hub: Hub = app.state.hub
        return {
            "ok": True,
            "kafka_ok": hub.kafka_ok,
            "clickhouse_ok": hub.ch_ok,
            "clients": len(hub.clients),
            "consumed": hub.consumed,
            "started_ms": hub.started_ms,
        }

    @app.get("/api/metrics")
    async def metrics():
        return await app.state.hub.metrics()

    @app.get("/api/debug/minute_counts")
    async def minute_counts(source: str = Query("wiki", pattern="^(wiki|usgs)$")):
        """网关按分钟去重计数 vs ClickHouse，verify_w2 用来做对数。"""
        hub: Hub = app.state.hub
        try:
            chc = await hub.ch.minute_counts(source)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": repr(exc)}, status_code=503)
        return {
            "started_ms": hub.started_ms,
            "gateway": {str(k): v for k, v in hub.minutes.snapshot(source).items()},
            "clickhouse": {str(k): v for k, v in chc.items()},
        }

    @app.get("/api/ask/status")
    async def ask_status():
        on = app.state.agent is not None
        return {
            "enabled": on,
            "provider": settings.llm_provider if on else None,
            "model": app.state.agent.llm.model if on else None,
        }

    @app.post("/api/ask")
    async def ask(body: AskBody, request: Request):
        from gateway.ai.agent import AskError

        agent = app.state.agent
        if agent is None:
            return JSONResponse(
                {"error": "AI 提问未开启：在 .env 设置 LLM_API_KEY"}, status_code=503
            )
        reason = app.state.limiter.check(_client_key(request))
        if reason:
            return JSONResponse({"error": reason}, status_code=429)
        sem: asyncio.Semaphore = app.state.ai_sem
        if sem.locked():
            return JSONResponse({"error": "当前提问人数较多，请稍后再试"}, status_code=429)
        async with sem:
            try:
                res = await agent.ask(body.question.strip())
            except AskError as exc:
                return JSONResponse({"error": str(exc)}, status_code=exc.status)
        return res.to_dict()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        hub: Hub = app.state.hub
        await ws.accept()
        if len(hub.clients) >= settings.max_clients:
            await ws.close(code=1013, reason="too many clients")
            return
        session = ClientSession(ws, settings)
        try:
            await hub.serve_client(session)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.info("client closed: %r", exc)

    static = Path(settings.static_dir)
    if (static / "index.html").exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    else:
        log.warning("static dir %s has no index.html; run `make web-build`", static)

        @app.get("/")
        async def no_web():
            return JSONResponse({"error": "前端未构建：先执行 make web-build"}, status_code=503)

    return app
