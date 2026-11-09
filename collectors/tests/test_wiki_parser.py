import json
from pathlib import Path

import pytest

from collectors.wiki.parser import RAW_WIKI_FIELDS, load_lang_region, parse_event

FIXTURE = Path(__file__).parent / "fixtures" / "wiki_recentchange.jsonl"
INGEST = 1762675300000


@pytest.fixture(scope="module")
def mapping():
    return load_lang_region()


@pytest.fixture(scope="module")
def events():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def test_filter_rules(events, mapping):
    out = [parse_event(e, mapping, INGEST) for e in events]
    kept = [r["event_id"][:8] for r in out if r is not None]
    # 保留：en edit / ja new / kk edit；丢弃：canary / wikidata / log / categorize
    assert kept == ["11111111", "22222222", "66666666"]


def test_contract_fields_exact(events, mapping):
    rec = parse_event(events[0], mapping, INGEST)
    assert tuple(rec.keys()) == RAW_WIKI_FIELDS


def test_never_outputs_user(events, mapping):
    for e in events:
        rec = parse_event(e, mapping, INGEST)
        if rec is not None:
            assert "user" not in rec


def test_edit_fields(events, mapping):
    rec = parse_event(events[0], mapping, INGEST)
    assert rec["lang"] == "en" and rec["wiki"] == "enwiki"
    assert rec["bytes_delta"] == 250
    assert rec["event_time_ms"] == 1762675200 * 1000  # timestamp 是秒
    assert rec["region"] == "United States"
    assert rec["lat"] == 39.8 and rec["lng"] == -98.6
    assert rec["url"] == "https://en.wikipedia.org/wiki/Example"
    assert rec["bot"] is False


def test_new_page_without_old_length(events, mapping):
    rec = parse_event(events[1], mapping, INGEST)
    assert rec["change_type"] == "new"
    assert rec["bytes_delta"] == 800


def test_unknown_lang(events, mapping):
    rec = parse_event(events[5], mapping, INGEST)
    assert rec["region"] == "Unknown"
    assert rec["lat"] is None and rec["lng"] is None
    assert rec["bytes_delta"] == -80
    assert rec["bot"] is True


@pytest.mark.parametrize("bad", [None, {}, {"meta": {}}, {"server_name": "en.wikipedia.org"}])
def test_bad_input_returns_none(bad, mapping):
    assert parse_event(bad, mapping, INGEST) is None


def test_mapping_file_valid(mapping):
    assert len(mapping) >= 20
    for lang, geo in mapping.items():
        assert isinstance(geo["region"], str) and geo["region"], lang
        assert -90 <= geo["lat"] <= 90, lang
        assert -180 <= geo["lng"] <= 180, lang
