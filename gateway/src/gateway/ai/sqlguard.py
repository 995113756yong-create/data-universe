"""AI 生成 SQL 的守卫。第一道防线（第二道是 ClickHouse 只读账号 du_ai，见迁移 004）。

规则：只允许单条 SELECT / UNION；只能读白名单表；禁止表函数、危险函数、SETTINGS / FORMAT / INTO；
最外层没有 LIMIT 时补 LIMIT，超过上限时压到上限。解析失败一律拒绝。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

ALLOWED_TABLES = frozenset({"events", "agg_minute", "alerts"})
ALLOWED_DBS = frozenset({"", "du"})
# 即使只读账号没有权限，也在这里先拦掉，给模型更明确的错误信息
DENY_FUNCS = frozenset(
    {
        "url",
        "file",
        "remote",
        "remotesecure",
        "s3",
        "s3cluster",
        "hdfs",
        "mysql",
        "postgresql",
        "jdbc",
        "odbc",
        "input",
        "executable",
        "cluster",
        "clusterallreplicas",
        "dictget",
        "azureblobstorage",
        "sleep",
        "sleepeachrow",
        "currentuser",
        "getsetting",
    }
)
MAX_LIMIT = 200
MAX_SQL_CHARS = 4000


class GuardError(ValueError):
    """SQL 未通过守卫，消息会原样回给模型，让它改写。"""


def check_sql(sql: str) -> str:
    """返回规范化后的安全 SQL（ClickHouse 方言，带 LIMIT）。不合规抛 GuardError。"""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise GuardError("SQL 为空")
    if len(sql) > MAX_SQL_CHARS:
        raise GuardError(f"SQL 过长（>{MAX_SQL_CHARS} 字符）")
    try:
        stmts = [s for s in sqlglot.parse(sql, read="clickhouse") if s is not None]
    except SqlglotError as exc:
        raise GuardError(f"SQL 解析失败：{str(exc)[:200]}") from exc
    if len(stmts) != 1:
        raise GuardError("只允许一条语句")
    tree = stmts[0]
    if not isinstance(tree, exp.Query):
        raise GuardError("只允许 SELECT 查询")
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Delete, exp.Update, exp.Create, exp.Drop, exp.Alter)):
            raise GuardError("只允许 SELECT 查询")
        if isinstance(node, exp.Into):
            raise GuardError("不允许 INTO")
    for q in tree.find_all(exp.Query):
        if q.args.get("settings"):
            raise GuardError("不允许 SETTINGS")
        if q.args.get("format"):
            raise GuardError("不允许 FORMAT")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            raise GuardError("不允许表函数")
        name, db = t.name.lower(), (t.db or "").lower()
        if t.catalog:
            raise GuardError(f"不允许访问 {t.sql('clickhouse')}")
        if db == "" and name in cte_names:
            continue
        if db not in ALLOWED_DBS or name not in ALLOWED_TABLES:
            raise GuardError(
                f"只能查询 du.events / du.agg_minute / du.alerts，不允许 {t.sql('clickhouse')}"
            )

    for f in tree.find_all(exp.Func):
        fname = (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()
        if fname in DENY_FUNCS:
            raise GuardError(f"不允许函数 {fname}")

    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_LIMIT)
    else:
        try:
            n = int(limit.expression.name)
        except (AttributeError, ValueError, TypeError):
            n = MAX_LIMIT + 1
        if n > MAX_LIMIT:
            tree = tree.limit(MAX_LIMIT)
    return tree.sql(dialect="clickhouse")
