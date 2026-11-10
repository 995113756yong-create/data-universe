import pytest

from collectors.config import Settings

UA = "DataUniverse/0.1 (https://github.com/me/data-universe; me@example.com)"


@pytest.fixture(autouse=True)
def base_env(monkeypatch):
    monkeypatch.setenv("HTTP_USER_AGENT", UA)
    monkeypatch.setenv("COLLECTORS", "usgs,wiki,opensky")
    for k in ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET", "OPENSKY_POLL_SECONDS"):
        monkeypatch.delenv(k, raising=False)


def test_anonymous_defaults():
    s = Settings.from_env()
    assert "opensky" in s.collectors
    assert not s.opensky_authenticated
    assert s.opensky_poll_seconds == 900


def test_oauth_defaults(monkeypatch):
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "me-api-client")
    monkeypatch.setenv("OPENSKY_CLIENT_SECRET", "s3cret")
    s = Settings.from_env()
    assert s.opensky_authenticated
    assert s.opensky_poll_seconds == 120


@pytest.mark.parametrize(
    "env",
    [
        {"OPENSKY_CLIENT_ID": "only-id"},
        {"OPENSKY_POLL_SECONDS": "300"},  # 匿名低于 900 秒会超额度
        {"OPENSKY_CLIENT_ID": "a", "OPENSKY_CLIENT_SECRET": "b", "OPENSKY_POLL_SECONDS": "30"},
    ],
)
def test_invalid(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValueError):
        Settings.from_env()
