"""USGS all_hour feed 轮询采集器。"""

from __future__ import annotations

import asyncio
import logging

import httpx

from collectors.backoff import backoff_delays
from collectors.config import TOPIC_USGS, Settings
from collectors.kafka_sink import KafkaSink
from collectors.metrics import Counter
from collectors.usgs.dedup import SeenCache
from collectors.usgs.parser import parse_feature
from collectors.utils import now_ms, sleep_or_stop

log = logging.getLogger("collectors.usgs")

FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"


async def run_usgs(
    sink: KafkaSink, settings: Settings, counter: Counter, stop: asyncio.Event
) -> None:
    cache = SeenCache()
    delays = None
    headers = {"User-Agent": settings.http_user_agent}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers=headers) as client:
        while not stop.is_set():
            try:
                resp = await client.get(FEED_URL)
                resp.raise_for_status()
                features = resp.json().get("features") or []
                ingest = now_ms()
                emitted = 0
                for feature in features:
                    rec = parse_feature(feature, ingest)
                    if rec is None:
                        counter.dropped += 1
                        continue
                    if not cache.should_emit(rec["event_id"], rec["updated_ms"]):
                        counter.filtered += 1
                        continue
                    await sink.send(TOPIC_USGS, rec["event_id"], rec, on_error=counter.on_error)
                    counter.sent += 1
                    emitted += 1
                log.debug("usgs poll ok: features=%d emitted=%d", len(features), emitted)
                delays = None
                wait = float(settings.usgs_poll_seconds)
            except (httpx.HTTPError, ValueError) as exc:
                counter.errors += 1
                delays = delays or backoff_delays(base=2.0, cap=300.0)
                wait = next(delays)
                log.warning("usgs poll failed: %r, retry in %.1fs", exc, wait)
            await sleep_or_stop(stop, wait)
