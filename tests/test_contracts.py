"""跨模块契约一致性检查：防止 Flink DDL、ClickHouse schema、网关协议各改各的。只用标准库。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLINK = ROOT / "streaming" / "flink-sql"
CH = ROOT / "storage" / "clickhouse" / "init" / "001_schema.sql"


def _table_block(sql: str, name: str) -> str:
    m = re.search(
        rf"CREATE TABLE (?:IF NOT EXISTS )?{re.escape(name)}\s*\((.*?)\)\s*(?:WITH|ENGINE)", sql, re.S
    )
    assert m, f"未找到表 {name}"
    return m.group(1)


def _columns(block: str) -> list[tuple[str, str]]:
    cols = []
    for line in block.splitlines():
        line = line.split("--")[0].strip().rstrip(",")
        if not line or line.upper().startswith(("WATERMARK", "INDEX")) or " AS " in line:
            continue
        name, typ = line.split(None, 1)
        cols.append((name.strip("`"), typ.strip()))
    return cols


def test_evt_unified_identical_in_both_flink_jobs():
    w1 = _columns(_table_block((FLINK / "00_ddl.sql").read_text(), "evt_unified"))
    w2 = _columns(_table_block((FLINK / "20_opensky_ddl.sql").read_text(), "evt_unified"))
    assert w1 == w2


def test_clickhouse_queue_matches_evt_unified():
    flink = [c for c, _ in _columns(_table_block((FLINK / "00_ddl.sql").read_text(), "evt_unified"))]
    ch = [c for c, _ in _columns(_table_block(CH.read_text(), "du.events_queue"))]
    assert flink == ch


def test_raw_opensky_ddl_matches_parser():
    import sys

    sys.path.insert(0, str(ROOT / "collectors" / "src"))
    from collectors.opensky.parser import RAW_OPENSKY_FIELDS

    ddl = [c for c, _ in _columns(_table_block((FLINK / "20_opensky_ddl.sql").read_text(), "raw_opensky"))]
    assert tuple(ddl) == RAW_OPENSKY_FIELDS


def test_raw_wiki_and_usgs_ddl_match_parsers():
    import sys

    sys.path.insert(0, str(ROOT / "collectors" / "src"))
    from collectors.usgs.parser import RAW_USGS_FIELDS
    from collectors.wiki.parser import RAW_WIKI_FIELDS

    sql = (FLINK / "00_ddl.sql").read_text()
    assert tuple(c for c, _ in _columns(_table_block(sql, "raw_usgs"))) == RAW_USGS_FIELDS
    assert tuple(c for c, _ in _columns(_table_block(sql, "raw_wiki"))) == RAW_WIKI_FIELDS


def test_migrations_are_numbered():
    files = sorted(p.name for p in (ROOT / "storage" / "clickhouse" / "migrations").glob("*.sql"))
    assert files, "至少应有一个迁移文件"
    assert all(re.match(r"^\d{3}_[a-z0-9_]+\.sql$", f) for f in files), files


MIG = ROOT / "storage" / "clickhouse" / "migrations"


def test_alert_sink_matches_clickhouse_queue():
    flink = [c for c, _ in _columns(_table_block((FLINK / "30_alerts_ddl.sql").read_text(), "alert_anomaly"))]
    ch = [c for c, _ in _columns(_table_block((MIG / "003_w3_alerts.sql").read_text(), "du.alerts_queue"))]
    assert flink == ch


def test_alert_sources_match_upstream():
    w1 = (FLINK / "00_ddl.sql").read_text()
    w3 = (FLINK / "30_alerts_ddl.sql").read_text()
    assert _columns(_table_block(w3, "raw_usgs_src")) == _columns(_table_block(w1, "raw_usgs"))
    agg = [c for c, _ in _columns(_table_block(w1, "agg_minute"))]
    assert [c for c, _ in _columns(_table_block(w3, "agg_minute_src"))] == agg


def test_alert_thresholds_documented():
    """阈值在 Flink SQL、verify_w3.py、contracts.md 三处必须一致。"""
    sql = (FLINK / "31_alerts_pipeline.sql").read_text()
    verify = (ROOT / "scripts" / "verify_w3.py").read_text()
    contracts = (ROOT / "docs" / "contracts.md").read_text()
    for token in (">= 3", "x - mean >= 10", "mag >= 4.5"):
        assert token in sql, token
    assert "n >= 11" in (FLINK / "30_alerts_ddl.sql").read_text()
    for token in ("Z_MIN = 3", "DELTA_MIN = 10", "BASELINE_MIN = 10", "QUAKE_MAG_MIN = 4.5"):
        assert token in verify, token
    for token in ("z ≥ 3", "≥ 10", "M4.5"):
        assert token in contracts, token


def test_region_centroids_cover_lang_mapping():
    import json

    langs = json.loads((ROOT / "collectors/src/collectors/wiki/lang_region.json").read_text())
    cent = json.loads((ROOT / "gateway/src/gateway/region_centroids.json").read_text())
    for k, v in langs.items():
        if k.startswith("_"):
            continue
        assert v["region"] in cent, v["region"]
        assert (cent[v["region"]]["lat"], cent[v["region"]]["lng"]) == (v["lat"], v["lng"])
