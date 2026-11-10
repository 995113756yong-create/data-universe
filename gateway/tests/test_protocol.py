from conftest import flight_evt, wiki_evt

from gateway.protocol import FLIGHT_FIELDS, POINT_FIELDS, encode


def test_wiki_row_matches_contract():
    layer, key, row = encode(wiki_evt(1))
    assert layer == "wiki" and key == "w1"
    assert len(row) == len(POINT_FIELDS)
    assert row[:6] == ["w1", 39.8, -98.6, 250.0, 1_794_281_538_000, 1_794_281_538_100]
    assert row[6] == "United States"


def test_flight_row_matches_contract():
    layer, key, row = encode(flight_evt("abc123", 1_794_281_538_000))
    assert layer == "opensky" and key == "abc123"
    assert len(row) == len(FLIGHT_FIELDS)
    d = dict(zip(FLIGHT_FIELDS, row, strict=True))
    assert d["heading_deg"] == 208.14 and d["velocity_ms"] == 225.78
    assert d["altitude_m"] == 10676 and d["callsign"] == "AFR123"


def test_flight_attrs_broken_falls_back():
    e = flight_evt("abc123", 1_000_000)
    e["attrs"] = "{not json"
    layer, key, row = encode(e)
    assert key == "abc123" and row[3] is None and row[8] == "AFR123"


def test_skip_without_coords_or_unknown_source():
    e = wiki_evt(1)
    e["lat"] = None
    assert encode(e) is None
    e = wiki_evt(2)
    e["source"] = "github"
    assert encode(e) is None
    assert encode(None) is None


def test_title_truncated():
    e = wiki_evt(1)
    e["title"] = "x" * 500
    assert len(encode(e)[2][7]) == 120
