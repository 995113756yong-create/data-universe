"""evt.unified 消费：不加入消费组、从最新位点开始（历史由 ClickHouse 快照补齐），断线自动重连。"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator

import orjson
from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

log = logging.getLogger("gateway.kafka")

TOPIC = "evt.unified"


def _loads(raw: bytes):
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError:
        return None


def kafka_source(bootstrap: str, hub) -> callable:
    async def gen() -> AsyncIterator[dict]:
        delay = 1.0
        while True:
            consumer = AIOKafkaConsumer(
                TOPIC,
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
                log.info("kafka consumer started on %s", TOPIC)
                async for msg in consumer:
                    if msg.value is not None:
                        yield msg.value
            except (KafkaError, OSError) as exc:
                log.warning("kafka error: %r, reconnect in %.1fs", exc, delay)
            finally:
                hub.kafka_ok = False
                await consumer.stop()
            await asyncio.sleep(random.uniform(0, delay))
            delay = min(delay * 2, 30.0)

    return gen
