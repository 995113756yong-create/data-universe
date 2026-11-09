"""运行配置：全部来自环境变量，启动时校验，配置错误直接退出。"""

from __future__ import annotations

import os
from dataclasses import dataclass

TOPIC_USGS = "raw.usgs"
TOPIC_WIKI = "raw.wiki"

KNOWN_COLLECTORS = ("usgs", "wiki")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    collectors: tuple[str, ...]
    kafka_bootstrap: str
    http_user_agent: str
    wiki_sample_rate: float
    usgs_poll_seconds: int
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        raw = _env("COLLECTORS", "usgs,wiki") or ""
        collectors = tuple(c.strip() for c in raw.split(",") if c.strip())
        unknown = sorted(set(collectors) - set(KNOWN_COLLECTORS))
        if not collectors or unknown:
            raise ValueError(f"COLLECTORS 非法: {raw!r}，可选值 {KNOWN_COLLECTORS}")

        ua = _env("HTTP_USER_AGENT")
        if not ua or "<" in ua:
            raise ValueError(
                "HTTP_USER_AGENT 未配置或仍是占位符。Wikimedia 要求 UA 带联系方式，"
                "例如: DataUniverse/0.1 (https://github.com/you/data-universe; you@example.com)"
            )

        rate = float(_env("WIKI_SAMPLE_RATE", "1.0") or "1.0")
        if not 0 < rate <= 1:
            raise ValueError("WIKI_SAMPLE_RATE 必须在 (0, 1] 区间")

        poll = int(_env("USGS_POLL_SECONDS", "60") or "60")
        if poll < 30:
            raise ValueError("USGS_POLL_SECONDS 不得小于 30（USGS feed 约每分钟更新一次）")

        return cls(
            collectors=collectors,
            kafka_bootstrap=_env("KAFKA_BOOTSTRAP", "redpanda:9092") or "redpanda:9092",
            http_user_agent=ua,
            wiki_sample_rate=rate,
            usgs_poll_seconds=poll,
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        )
