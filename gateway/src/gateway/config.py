from __future__ import annotations

import os
from dataclasses import dataclass

LAYERS = ("wiki", "usgs", "opensky")

# OpenAI 兼容接口预设。LLM_BASE_URL / LLM_MODEL 可覆盖；provider=custom 时两者必填。
LLM_PRESETS: dict[str, tuple[str, str]] = {
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "kimi": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class GatewaySettings:
    kafka_bootstrap: str = "redpanda:9092"
    clickhouse_url: str = "http://clickhouse:8123"
    clickhouse_user: str = "du"
    clickhouse_password: str = "du_dev"
    static_dir: str = "/app/static"
    host: str = "0.0.0.0"
    port: int = 8090
    tick_ms: int = 200
    wiki_cap: int = 200  # 每个 tick、每个客户端最多推送的维基点数（即 1000 点/秒）
    wiki_cap_min: int = 20
    flight_cap: int = 2500  # 每个 tick 最多推送的航班更新数，其余留到下个 tick
    flight_window_s: int = 1200  # 超过该时间没有新位置的飞机视为离开
    metrics_interval_s: float = 2.0
    ch_cache_s: float = 10.0
    max_clients: int = 50
    # ---- W3 AI 提问（LLM_API_KEY 为空时关闭） ----
    llm_provider: str = "deepseek"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_s: int = 30
    ai_per_min: int = 5
    ai_per_day: int = 300
    ai_concurrency: int = 3
    ai_ch_user: str = "du_ai"
    ai_ch_password: str = "du_ai_dev"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @classmethod
    def from_env(cls) -> GatewaySettings:
        d = cls()
        s = cls(
            kafka_bootstrap=os.getenv("KAFKA_BOOTSTRAP", d.kafka_bootstrap),
            clickhouse_url=os.getenv("CLICKHOUSE_URL", d.clickhouse_url),
            clickhouse_user=os.getenv("CLICKHOUSE_USER", d.clickhouse_user),
            clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", d.clickhouse_password),
            static_dir=os.getenv("STATIC_DIR", d.static_dir),
            port=_int("GATEWAY_PORT", d.port),
            tick_ms=_int("TICK_MS", d.tick_ms),
            wiki_cap=_int("WIKI_CAP", d.wiki_cap),
            flight_cap=_int("FLIGHT_CAP", d.flight_cap),
            flight_window_s=_int("FLIGHT_WINDOW_S", d.flight_window_s),
            llm_provider=os.getenv("LLM_PROVIDER", d.llm_provider).strip().lower()
            or d.llm_provider,
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_timeout_s=_int("LLM_TIMEOUT_S", d.llm_timeout_s),
            ai_per_min=_int("AI_PER_MIN", d.ai_per_min),
            ai_per_day=_int("AI_PER_DAY", d.ai_per_day),
            ai_ch_user=os.getenv("AI_CH_USER", d.ai_ch_user),
            ai_ch_password=os.getenv("AI_CH_PASSWORD", d.ai_ch_password),
        )
        s = s.with_llm_defaults()
        if not 50 <= s.tick_ms <= 1000:
            raise ValueError("TICK_MS 必须在 50~1000 之间")
        if s.wiki_cap < s.wiki_cap_min or s.flight_cap < 100:
            raise ValueError("WIKI_CAP / FLIGHT_CAP 过小")
        return s

    def with_llm_defaults(self) -> GatewaySettings:
        """按 provider 补全 base_url / model。provider 未知且未给 base_url 时报错。"""
        from dataclasses import replace

        if self.llm_base_url and self.llm_model:
            return self
        preset = LLM_PRESETS.get(self.llm_provider)
        if preset is None:
            if not self.ai_enabled:
                return self
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider} 不是预设（{', '.join(LLM_PRESETS)}），"
                "需同时设置 LLM_BASE_URL 和 LLM_MODEL"
            )
        return replace(
            self,
            llm_base_url=self.llm_base_url or preset[0],
            llm_model=self.llm_model or preset[1],
        )
