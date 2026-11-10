import gzip
import json

import orjson
import pytest

from gateway.replay_export import (
    CHUNK_MS,
    EVENT_KEYS,
    FLIGHT_PREROLL_MS,
    build_chunks,
    encode_events,
    parse_end,
    update_index,
    write_bundle,
)

S = 1_794_300_000_000 - 1_794_300_000_000 % CHUNK_MS


def raw(source, eid, t, attrs=""):
    vals = {
        "event_id": eid,
        "source": source,
        "lat": 10.0,
        "lng": 20.0,
        "weight": 5.0,
        "event_time_ms": str(t),
        "ingest_time_ms": str(t + 500),
        "region": "Japan",
        "title": "Some title",
        "url": "https://x",
        "attrs": attrs,
    }
    return [vals[k] for k in EVENT_KEYS]


def test_encode_dedup_and_strip_wiki_text():
    out = encode_events(
        [
            raw("wiki", "w1", S),
            raw("wiki", "w1", S),
            raw("usgs", "q1", S),
            raw(
                "opensky",
                "abc-1",
                S,
                '{"icao24":"abc","heading_deg":90,"velocity_ms":200,"callsign":"CCA1"}',
            ),
            raw("nope", "x", S),
        ]
    )
    assert len(out["wiki"]) == 1 and out["wiki"][0][7] == "" and out["wiki"][0][8] == ""
    assert out["usgs"][0][7] == "Some title"  # 地震保留标题
    assert out["opensky"][0][0] == "abc" and out["opensky"][0][8] == "CCA1"
    assert out["wiki"][0][4] == S  # 字符串时间戳转成 int


def test_build_chunks_assignment():
    layers = encode_events(
        [
            raw("wiki", "a", S + 61_000),
            raw("wiki", "b", S + 5_000),
            raw("wiki", "old", S - 1),  # 早于开始：丢弃
            raw("wiki", "late", S + 3 * CHUNK_MS),  # 超出：丢弃
            raw("opensky", "p-1", S - 60_000, '{"icao24":"p"}'),  # 预热：进第 0 片
            raw("opensky", "q-1", S - FLIGHT_PREROLL_MS - 1, '{"icao24":"q"}'),  # 太早：丢弃
            raw("opensky", "r-1", S + 2 * CHUNK_MS + 1, '{"icao24":"r"}'),
        ]
    )
    chunks = build_chunks(layers, S, S + 3 * CHUNK_MS)
    assert [c["t0"] for c in chunks] == [S, S + CHUNK_MS, S + 2 * CHUNK_MS]
    assert [r[0] for r in chunks[0]["wiki"]] == ["b"]
    assert [r[0] for r in chunks[1]["wiki"]] == ["a"]
    assert [r[0] for r in chunks[0]["opensky"]] == ["p"]
    assert [r[0] for r in chunks[2]["opensky"]] == ["r"]


def test_chunks_sorted_within():
    layers = encode_events([raw("wiki", "x", S + 30_000), raw("wiki", "y", S + 10_000)])
    c = build_chunks(layers, S, S + CHUNK_MS)[0]
    assert [r[0] for r in c["wiki"]] == ["y", "x"]


def test_write_bundle_and_index(tmp_path):
    chunks = build_chunks(encode_events([raw("wiki", "a", S + 1)]), S, S + 2 * CHUNK_MS)
    total = write_bundle(tmp_path, "r1", {"v": 1, "start_ms": S}, chunks)
    m = json.loads((tmp_path / "r1" / "manifest.json").read_text())
    assert [c["file"] for c in m["chunks"]] == ["chunks/00000.json.gz", "chunks/00001.json.gz"]
    assert m["chunks"][0]["n"] == {"wiki": 1, "opensky": 0}
    c0 = orjson.loads(gzip.decompress((tmp_path / "r1/chunks/00000.json.gz").read_bytes()))
    assert c0["t0"] == S and c0["wiki"][0][0] == "a"
    assert total > 0
    update_index(tmp_path, {"id": "r1", "start_ms": 1}, keep=2)
    update_index(tmp_path, {"id": "r2", "start_ms": 3}, keep=2)
    update_index(tmp_path, {"id": "r1", "start_ms": 1, "title": "again"}, keep=2)
    items = update_index(tmp_path, {"id": "r3", "start_ms": 2}, keep=2)
    assert [e["id"] for e in items] == ["r2", "r3"]


def test_gzip_deterministic():
    from gateway.replay_export import gz_json

    assert gz_json({"a": 1}) == gz_json({"a": 1})  # mtime=0：重复导出内容不变，git diff 干净


def test_parse_end():
    now = S + 5 * CHUNK_MS + 12_345
    assert parse_end("now", now) == S + 3 * CHUNK_MS
    assert parse_end("2026-11-10T08:00:30Z", now) % CHUNK_MS == 0
    assert parse_end("2026-11-10T08:00:30", now) == parse_end("2026-11-10T08:00:00+00:00", now)
    with pytest.raises(ValueError):
        parse_end("yesterday", now)
