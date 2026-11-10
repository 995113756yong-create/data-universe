"""运行配置：全部来自环境变量，启动时校验，配置错误直接退出。"""

from __future__ import annotations

import os
from dataclasses import dataclass

TOPIC_USGS = "raw.usgs"
TOPIC_WIKI = "raw.wiki"
TOPIC_OPENSKY = "raw.opensky"

KNOWN_COLLECTORS = ("usgs", "wiki", "opensky")

# OpenSky 额度（以官方文档为准）：匿名 400 点/天，注册账号 4000 点/天；全球 states/all 一次 4 点。
OPENSKY_MIN_POLL_AUTH = 90
OPENSKY_MIN_POLL_ANON = 900


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
    opensky_client_id: str | None = None
    opensky_client_secret: str | None = None
    opensky_poll_seconds: int = OPENSKY_MIN_POLL_ANON

    @property
    def opensky_authenticated(self) -> bool:
        return bool(self.opensky_client_id and self.opensky_client_secret)

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

        os_id = _env("OPENSKY_CLIENT_ID")
        os_secret = _env("OPENSKY_CLIENT_SECRET")
        if bool(os_id) != bool(os_secret):
            raise ValueError("OPENSKY_CLIENT_ID 与 OPENSKY_CLIENT_SECRET 必须同时配置或同时留空")
        os_min = OPENSKY_MIN_POLL_AUTH if os_id else OPENSKY_MIN_POLL_ANON
        os_poll = int(_env("OPENSKY_POLL_SECONDS", str(max(os_min, 120))) or os_min)
        if os_poll < os_min:
            raise ValueError(
                f"OPENSKY_POLL_SECONDS={os_poll} 会超出 OpenSky 每日额度："
                f"{'注册账号' if os_id else '匿名访问'}最小 {os_min} 秒"
            )

        return cls(
            opensky_client_id=os_id,
            opensky_client_secret=os_secret,
            opensky_poll_seconds=os_poll,
            collectors=collectors,
            kafka_bootstrap=_env("KAFKA_BOOTSTRAP", "redpanda:9092") or "redpanda:9092",
            http_user_agent=ua,
            wiki_sample_rate=rate,
            usgs_poll_seconds=poll,
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        )
