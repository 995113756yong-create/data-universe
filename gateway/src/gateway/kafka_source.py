"""消费 evt.unified 与 alert.anomaly。

不加入消费组、从最新位点开始（历史由 ClickHouse 快照补齐），断线自动重连。

产出 (topic, value) 元组。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Callable

import orjson
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

log = logging.getLogger("gateway.kafka")

TOPIC_EVENTS = "evt.unified"
TOPIC_ALERTS = "alert.anomaly"


def _loads(raw: bytes):
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None


def kafka_source(bootstrap: str, hub) -> Callable[[], AsyncIterator[tuple[str, dict]]]:
    async def gen() -> AsyncIterator[tuple[str, dict]]:
        delay = 1.0
        while True:
            consumer = AIOKafkaConsumer(
                TOPIC_EVENTS,
                TOPIC_ALERTS,
                bootstrap_servers=bootstrap,
                group_id=None,
                auto_offset_reset="latest",
                enable_auto_commit=False,
                value_deserializer=_loads,
            )
            try:
                await consumer.start()
                hub.kafka_ok = True
                delay = 1.0
                log.info("kafka consumer started on %s, %s", TOPIC_EVENTS, TOPIC_ALERTS)
                async for msg in consumer:
                    if msg.value is not None:
                        yield msg.topic, msg.value
            except (KafkaError, OSError) as exc:
                log.warning("kafka error: %r, reconnect in %.1fs", exc, delay)
            finally:
                hub.kafka_ok = False
                await consumer.stop()
            await asyncio.sleep(random.uniform(0, delay))
            delay = min(delay * 2, 30.0)

    return gen
