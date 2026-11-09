"""Wikimedia EventStreams (SSE) 采集器，断线后带 Last-Event-ID 续传。"""

from __future__ import annotations

import asyncio
import json
import logging
import random

import httpx
from httpx_sse import SSEError, aconnect_sse

from collectors.backoff import backoff_delays
from collectors.config import TOPIC_WIKI, Settings
from collectors.kafka_sink import KafkaSink
from collectors.metrics import Counter
from collectors.utils import now_ms, sleep_or_stop
from collectors.wiki.parser import load_lang_region, parse_event

log = logging.getLogger("collectors.wiki")

STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"


async def run_wiki(
    sink: KafkaSink, settings: Settings, counter: Counter, stop: asyncio.Event
) -> None:
    mapping = load_lang_region()
    rng = random.Random()
    sample_rate = settings.wiki_sample_rate
    last_event_id: str | None = None
    delays = None
    # read=60s：流长时间无数据视为假死，触发重连
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
    headers = {"User-Agent": settings.http_user_agent}

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while not stop.is_set():
            req_headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
            try:
                async with aconnect_sse(client, "GET", STREAM_URL, headers=req_headers) as es:
                    es.response.raise_for_status()
                    log.info("wiki stream connected (resume=%s)", bool(last_event_id))
                    delays = None
                    async for sse in es.aiter_sse():
                        if stop.is_set():
                            break
                        if sse.id:
                            last_event_id = sse.id
                        if sse.event != "message" or not sse.data:
                            continue
                        try:
                            evt = json.loads(sse.data)
                        except ValueError:
                            counter.dropped += 1
                            continue
                        rec = parse_event(evt, mapping, now_ms())
                        if rec is None:
                            counter.filtered += 1
                            continue
                        if sample_rate < 1 and rng.random() > sample_rate:
                            counter.filtered += 1
                            continue
                        await sink.send(TOPIC_WIKI, rec["event_id"], rec, on_error=counter.on_error)
                        counter.sent += 1
                wait = 1.0  # 服务端正常断开（约每十几分钟一次），快速重连
                log.info("wiki stream closed by server, reconnecting")
            except (httpx.HTTPError, SSEError) as exc:
                counter.errors += 1
                delays = delays or backoff_delays(base=1.0, cap=60.0)
                wait = next(delays)
                log.warning("wiki stream error: %r, retry in %.1fs", exc, wait)
            await sleep_or_stop(stop, wait)
