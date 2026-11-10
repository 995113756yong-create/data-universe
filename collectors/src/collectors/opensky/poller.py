"""OpenSky 全球 states/all 轮询采集器。"""

from __future__ import annotations

import asyncio
import logging

import httpx

from collectors.backoff import backoff_delays
from collectors.config import TOPIC_OPENSKY, Settings
from collectors.kafka_sink import KafkaSink
from collectors.metrics import Counter
from collectors.opensky.auth import TokenProvider
from collectors.opensky.parser import parse_response
from collectors.usgs.dedup import SeenCache  # 通用的「按版本去重」缓存，W1 已有，复用
from collectors.utils import now_ms, sleep_or_stop

log = logging.getLogger("collectors.opensky")

STATES_URL = "https://opensky-network.org/api/states/all"


def retry_after_seconds(resp: httpx.Response, default: float) -> float:
    raw = resp.headers.get("X-Rate-Limit-Retry-After-Seconds")
    try:
        return max(float(raw), 1.0) if raw is not None else default
    except ValueError:
        return default


async def run_opensky(
    sink: KafkaSink, settings: Settings, counter: Counter, stop: asyncio.Event
) -> None:
    tokens = (
        TokenProvider(settings.opensky_client_id, settings.opensky_client_secret)
        if settings.opensky_authenticated
        else None
    )
    log.info(
        "opensky mode=%s poll=%ss",
        "oauth" if tokens else "anonymous",
        settings.opensky_poll_seconds,
    )
    cache = SeenCache(max_size=50_000)  # 同一架飞机 time_position 不变就不重发
    delays = None
    headers = {"User-Agent": settings.http_user_agent}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), headers=headers) as client:
        while not stop.is_set():
            wait = float(settings.opensky_poll_seconds)
            try:
                req_headers = {}
                if tokens is not None:
                    req_headers["Authorization"] = f"Bearer {await tokens.get(client)}"
                resp = await client.get(STATES_URL, headers=req_headers)
                if resp.status_code == 429:
                    wait = retry_after_seconds(resp, wait)
                    counter.errors += 1
                    log.warning("opensky rate limited, retry after %.0fs", wait)
                elif resp.status_code == 401 and tokens is not None:
                    tokens.invalidate()
                    counter.errors += 1
                    wait = 5.0
                    log.warning("opensky token rejected, refreshing")
                else:
                    resp.raise_for_status()
                    records, filtered = parse_response(resp.json(), now_ms())
                    counter.filtered += filtered
                    emitted = 0
                    for rec in records:
                        if not cache.should_emit(rec["icao24"], rec["event_time_ms"]):
                            counter.filtered += 1
                            continue
                        await sink.send(
                            TOPIC_OPENSKY, rec["event_id"], rec, on_error=counter.on_error
                        )
                        counter.sent += 1
                        emitted += 1
                    log.info(
                        "opensky poll ok: emitted=%d filtered=%d remaining_credits=%s",
                        emitted,
                        filtered,
                        resp.headers.get("X-Rate-Limit-Remaining", "?"),
                    )
                    delays = None
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                counter.errors += 1
                delays = delays or backoff_delays(base=5.0, cap=600.0)
                wait = next(delays)
                log.warning("opensky poll failed: %r, retry in %.1fs", exc, wait)
            await sleep_or_stop(stop, wait)
