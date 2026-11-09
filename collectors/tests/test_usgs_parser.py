import json
from pathlib import Path

import pytest

from collectors.usgs.dedup import SeenCache
from collectors.usgs.parser import RAW_USGS_FIELDS, derive_region, parse_feature

FIXTURE = Path(__file__).parent / "fixtures" / "usgs_all_hour.json"
INGEST = 1762675300000


@pytest.fixture(scope="module")
def features():
    return json.loads(FIXTURE.read_text())["features"]


def test_contract_fields_exact(features):
    rec = parse_feature(features[0], INGEST)
    assert rec is not None
    assert tuple(rec.keys()) == RAW_USGS_FIELDS  # 契约字段与顺序不得改变


def test_parse_normal(features):
    rec = parse_feature(features[0], INGEST)
    assert rec["event_id"] == "ci40000001"
    assert rec["mag"] == 2.4
    assert rec["lat"] == 35.55 and rec["lng"] == -117.75  # GeoJSON 坐标是 [lng, lat, depth]
    assert rec["depth_km"] == 8.2
    assert rec["event_time_ms"] == 1762675000000
    assert rec["updated_ms"] == 1762675100000
    assert rec["ingest_time_ms"] == INGEST
    assert rec["region"] == "United States"
    assert rec["quake_type"] == "earthquake"


def test_null_mag_kept(features):
    rec = parse_feature(features[2], INGEST)
    assert rec is not None and rec["mag"] is None
    assert rec["url"] == ""


def test_missing_updated_and_depth(features):
    rec = parse_feature(features[3], INGEST)
    assert rec["updated_ms"] == rec["event_time_ms"]
    assert rec["depth_km"] is None
    assert rec["mag"] == -0.3  # 负震级原样保留，weight 在 Flink 里截断为 0
    assert rec["quake_type"] == "quarry blast"
    assert rec["region"] == "Mexico"


def test_missing_geometry_dropped(features):
    assert parse_feature(features[4], INGEST) is None


@pytest.mark.parametrize("bad", [None, {}, {"id": "x"}, {"id": "x", "properties": {"time": 1}}])
def test_bad_input_returns_none(bad):
    assert parse_feature(bad, INGEST) is None


@pytest.mark.parametrize(
    "place, expected",
    [
        ("10 km SW of Ridgecrest, CA", "United States"),
        ("45 km W of Anchor Point, Alaska", "United States"),
        ("3 km N of Some Town, New Mexico", "United States"),
        ("Mid-Atlantic Ridge", "Mid-Atlantic Ridge"),
        ("120 km E of Hualien City, Taiwan", "Taiwan"),
        ("5 km S of Ensenada, B.C., MX", "Mexico"),
        ("", "Unknown"),
        (None, "Unknown"),
    ],
)
def test_derive_region(place, expected):
    assert derive_region(place) == expected


def test_seen_cache_dedup_and_revision():
    c = SeenCache(max_size=2)
    assert c.should_emit("a", 100) is True
    assert c.should_emit("a", 100) is False  # 同版本不重发
    assert c.should_emit("a", 90) is False  # 旧版本不重发
    assert c.should_emit("a", 200) is True  # 修订后重发
    assert c.should_emit("b", 1) is True
    assert c.should_emit("c", 1) is True  # 超出容量，淘汰最久未访问的 a
    assert len(c) == 2
    assert c.should_emit("a", 200) is True
