"""Kafka 生产者封装：acks=all + 幂等，key 为 event_id，value 为 JSON。"""

from __future__ import annotations

from collections.abc import Callable

import orjson
from aiokafka import AIOKafkaProducer


class KafkaSink:
    def __init__(self, bootstrap: str) -> None:
        self._bootstrap = bootstrap
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            acks="all",
            enable_idempotence=True,
            linger_ms=50,
            compression_type="gzip",
            key_serializer=lambda k: k.encode("utf-8"),
            value_serializer=orjson.dumps,
        )
        try:
            await producer.start()
        except Exception:
            await producer.stop()
            raise
        self._producer = producer

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()  # stop() 会先 flush 缓冲区
            self._producer = None

    async def send(
        self,
        topic: str,
        key: str,
        value: dict,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaSink 未启动")
        fut = await self._producer.send(topic, key=key, value=value)
        if on_error is not None:

            def _cb(f) -> None:
                if not f.cancelled() and f.exception() is not None:
                    on_error(f.exception())

            fut.add_done_callback(_cb)
