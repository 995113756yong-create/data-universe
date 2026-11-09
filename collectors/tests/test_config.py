import pytest

from collectors.config import Settings

UA = "DataUniverse/0.1 (https://github.com/me/data-universe; me@example.com)"


def test_defaults(monkeypatch):
    monkeypatch.setenv("HTTP_USER_AGENT", UA)
    for k in ("COLLECTORS", "WIKI_SAMPLE_RATE", "USGS_POLL_SECONDS", "KAFKA_BOOTSTRAP"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.collectors == ("usgs", "wiki")
    assert s.kafka_bootstrap == "redpanda:9092"
    assert s.usgs_poll_seconds == 60


@pytest.mark.parametrize(
    "env",
    [
        {"HTTP_USER_AGENT": ""},
        {"HTTP_USER_AGENT": "DataUniverse/0.1 (<your-github>)"},
        {"HTTP_USER_AGENT": UA, "COLLECTORS": "usgs,foo"},
        {"HTTP_USER_AGENT": UA, "WIKI_SAMPLE_RATE": "0"},
        {"HTTP_USER_AGENT": UA, "USGS_POLL_SECONDS": "5"},
    ],
)
def test_invalid(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValueError):
        Settings.from_env()
