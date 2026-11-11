import pytest

from gateway.ai.sqlguard import MAX_LIMIT, GuardError, check_sql

OK = [
    "SELECT region, uniqExact(event_id) AS c FROM du.events WHERE source = 'wiki' "
    "AND event_time > now() - INTERVAL 1 HOUR GROUP BY region ORDER BY c DESC LIMIT 10",
    "SELECT * FROM du.alerts FINAL ORDER BY event_time DESC LIMIT 5",
    "WITH t AS (SELECT region, sum(event_cnt) c FROM du.agg_minute FINAL GROUP BY region) "
    "SELECT * FROM t ORDER BY c DESC",
    "SELECT JSONExtractFloat(attrs, 'mag') AS mag, title FROM events WHERE source='usgs'",
    "SELECT 1 UNION ALL SELECT 2",
    "select count() from du.events;",
]

BAD = [
    ("", "为空"),
    ("SELECT 1; DROP TABLE du.events", "一条"),
    ("DROP TABLE du.events", ""),
    ("INSERT INTO du.events SELECT * FROM du.events", ""),
    ("SELECT * FROM system.users", "只能查询"),
    ("SELECT * FROM default.secret", "只能查询"),
    ("SELECT * FROM du.events_queue", "只能查询"),
    ("SELECT * FROM url('http://evil', CSV, 'a String')", "表函数"),
    ("SELECT * FROM remote('h', du.events)", "表函数"),
    ("SELECT file('/etc/passwd')", "file"),
    ("SELECT sleep(3)", "sleep"),
    ("SELECT 1 SETTINGS max_execution_time = 1000", "SETTINGS"),
    ("SELECT 1 FORMAT TSV", "FORMAT"),
    ("SELECT * FROM du.events INTO OUTFILE 'x'", ""),
    ("SELECT * FROM (SELECT * FROM system.tables)", "只能查询"),
    ("SELECT x FROM du.events WHERE event_id IN (SELECT name FROM system.users)", "只能查询"),
    ("SELECT " + "1+" * 3000 + "1", "过长"),
]


@pytest.mark.parametrize("sql", OK)
def test_allowed(sql):
    out = check_sql(sql)
    assert "LIMIT" in out.upper()


@pytest.mark.parametrize("sql,why", BAD)
def test_rejected(sql, why):
    with pytest.raises(GuardError) as e:
        check_sql(sql)
    assert why in str(e.value)


def test_limit_added_and_capped():
    assert f"LIMIT {MAX_LIMIT}" in check_sql("SELECT * FROM du.events")
    assert f"LIMIT {MAX_LIMIT}" in check_sql("SELECT * FROM du.events LIMIT 100000")
    assert "LIMIT 7" in check_sql("SELECT * FROM du.events LIMIT 7")


def test_cte_name_cannot_shadow_system():
    with pytest.raises(GuardError):
        check_sql("WITH users AS (SELECT 1) SELECT * FROM system.users")
