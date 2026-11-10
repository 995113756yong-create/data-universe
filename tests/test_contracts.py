"""跨模块契约一致性检查：防止 Flink DDL、ClickHouse schema、网关协议各改各的。只用标准库。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLINK = ROOT / "streaming" / "flink-sql"
CH = ROOT / "storage" / "clickhouse" / "init" / "001_schema.sql"


def _table_block(sql: str, name: str) -> str:
    m = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{re.escape(name)}\s*\((.*?)\)\s*(?:WITH|ENGINE)", sql, re.S)
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
