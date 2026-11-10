"""入口：按 COLLECTORS 并发运行采集器；任一采集器异常退出则整体退出（由 docker 重启）。"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiokafka.errors import KafkaError

from collectors.backoff import backoff_delays
from collectors.config import Settings
from collectors.kafka_sink import KafkaSink
from collectors.metrics import Counter, report_forever
from collectors.opensky.poller import run_opensky
from collectors.usgs.poller import run_usgs
from collectors.utils import sleep_or_stop
from collectors.wiki.sse_client import run_wiki

log = logging.getLogger("collectors")

RUNNERS = {"usgs": run_usgs, "wiki": run_wiki, "opensky": run_opensky}


async def _start_sink(sink: KafkaSink, stop: asyncio.Event) -> bool:
    delays = backoff_delays(base=1.0, cap=30.0)
    while not stop.is_set():
        try:
            await sink.start()
            log.info("kafka producer started")
            return True
        except (KafkaError, OSError) as exc:
            wait = next(delays)
            log.warning("kafka not ready: %r, retry in %.1fs", exc, wait)
            await sleep_or_stop(stop, wait)
    return False


async def amain() -> int:
    settings = Settings.from_env()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    sink = KafkaSink(settings.kafka_bootstrap)
    if not await _start_sink(sink, stop):
        return 0

    counters = {name: Counter(name) for name in settings.collectors}
    tasks = [
        asyncio.create_task(RUNNERS[name](sink, settings, counters[name], stop), name=name)
        for name in settings.collectors
    ]
    reporter = asyncio.create_task(report_forever(list(counters.values())))
    stop_task = asyncio.create_task(stop.wait())
    exit_code = 0
    try:
        done, _ = await asyncio.wait([*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t is not stop_task and not t.cancelled() and t.exception() is not None:
                log.error("collector %s crashed", t.get_name(), exc_info=t.exception())
                exit_code = 1
        stop.set()
        await asyncio.wait(tasks, timeout=15)
    finally:
        for t in (*tasks, reporter, stop_task):
            if not t.done():
                t.cancel()
        await sink.stop()
        log.info("collectors stopped, exit_code=%d", exit_code)
    return exit_code


def main() -> None:
    try:
        sys.exit(asyncio.run(amain()))
    except ValueError as exc:  # 配置错误
        print(f"[config error] {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
