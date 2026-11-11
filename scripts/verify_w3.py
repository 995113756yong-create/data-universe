#!/usr/bin/env python3
r"""W3 端到端验收。全部 PASS 才算 W3 完成。不允许调低阈值、删检查项、跳过检查项。

前提：make up 之后至少运行 40 分钟（维基激增需要 30 分钟基线），已 make ch-migrate、make web-build、
      已在 .env 配置 LLM_API_KEY 并重启 gateway，已 make replay-export 导出演示回放。
运行：gateway/.venv/bin/python scripts/verify_w3.py   （Windows: gateway\.venv\Scripts\python.exe）
唯一允许的跳过：仓库所有者本人在 shell 里设置 VERIFY_SKIP_AI=1（Agent 不得自行设置）。
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GATEWAY = "http://localhost:8090"
WS_URL = "ws://localhost:8090/ws"
FLINK = "http://localhost:8081"
CH_URL = "http://localhost:8123"
ROOT = Path(__file__).resolve().parents[1]
JOBS = ("data-universe-w1", "data-universe-w2-opensky", "data-universe-w3-alerts")

# 告警阈值：必须与 streaming/flink-sql/30_alerts_ddl.sql、31_alerts_pipeline.sql、docs/contracts.md 一致
Z_MIN = 3
DELTA_MIN = 10
BASELINE_MIN = 10
QUAKE_MAG_MIN = 4.5
WINDOW_S = 1800

THRESHOLDS = {
    "spike_jaccard_min": 0.9,  # Flink 告警 vs ClickHouse 独立重算
    "ask_max_s": 30.0,
    "replay_min_minutes": 30,
    "replay_max_mb": 30.0,
    "replay_min_qa": 3,
}

failed = False


def ok(msg: str) -> None:
    print(f"\033[32mPASS\033[0m  {msg}")


def bad(msg: str) -> None:
    global failed
    failed = True
    print(f"\033[31mFAIL\033[0m  {msg}")


def info(msg: str) -> None:
    print(f"      {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else bad)(msg)


def section(title: str) -> None:
    print(f"\n== {title} ==")


def http_json(url: str, body: dict | None = None, timeout: float = 15):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def ch(sql: str, user: str = "du", password: str = "du_dev") -> list[list]:
    """返回 JSONCompact data；出错抛 RuntimeError（消息为 ClickHouse 错误文本）。"""
    q = urllib.parse.urlencode({"database": "du"})
    req = urllib.request.Request(
        f"{CH_URL}/?{q}",
        data=(sql + "\nFORMAT JSONCompact").encode(),
        headers={"X-ClickHouse-User": user, "X-ClickHouse-Key": password},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())["data"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode(errors="replace")[:300]) from e


# ---------------------------------------------------------------- 1. 作业与表
def check_infra() -> int | None:
    section("1. Flink 作业 / ClickHouse 对象")
    alerts_start = None
    try:
        _, ov = http_json(f"{FLINK}/jobs/overview")
        for name in JOBS:
            running = [j for j in ov["jobs"] if j["name"] == name and j["state"] == "RUNNING"]
            check(len(running) == 1, f"Flink 作业 {name} 恰好 1 个 RUNNING（实际 {len(running)}）")
            if name == JOBS[2] and running:
                alerts_start = int(running[0]["start-time"])
    except Exception as exc:  # noqa: BLE001
        bad(f"Flink REST 不可用：{exc!r}")
    try:
        names = {r[0] for r in ch("SELECT name FROM system.tables WHERE database = 'du'")}
        for t in ("alerts", "alerts_queue", "alerts_mv"):
            check(t in names, f"du.{t} 存在（迁移 003）")
        users = {r[0] for r in ch("SELECT name FROM system.users")}
        check("du_ai" in users, "只读账号 du_ai 存在（迁移 004）")
    except RuntimeError as exc:
        bad(f"ClickHouse 查询失败：{exc}")
    return alerts_start


# ---------------------------------------------------------------- 2. 只读账号
def check_ai_account() -> None:
    section("2. du_ai 只读账号（SQL 守卫之外的第二道防线）")
    pw = os.getenv("AI_CH_PASSWORD", "du_ai_dev")
    try:
        n = ch("SELECT count() FROM du.alerts", "du_ai", pw)[0][0]
        ok(f"du_ai 可以读 du.alerts（{n} 行）")
    except RuntimeError as exc:
        bad(f"du_ai 读 du.alerts 失败：{exc}")
    must_fail = {
        "写入": "INSERT INTO du.alerts (alert_id) VALUES ('verify-should-fail')",
        "读系统用户表": "SELECT name FROM system.users",
        "读未授权表（W1 Kafka 队列表的定义）": "SHOW CREATE TABLE du.events_queue",
        "表函数 url()": "SELECT * FROM url('http://example.com', CSV, 'a String')",
        "突破执行时间上限": "SELECT 1 SETTINGS max_execution_time = 1000",
    }
    for what, sql in must_fail.items():
        try:
            ch(sql, "du_ai", pw)
            bad(f"du_ai 不应允许：{what}")
        except RuntimeError:
            ok(f"du_ai 拒绝：{what}")


# ---------------------------------------------------------------- 3. 告警对账
def check_quake_alerts() -> None:
    section("3a. 显著地震告警：每个 M4.5+ 地震都有告警")
    try:
        rows = ch(f"""
            SELECT event_id FROM du.events FINAL
            WHERE source = 'usgs' AND weight >= {QUAKE_MAG_MIN}
              AND ingest_time BETWEEN now64(3) - INTERVAL 20 HOUR AND now64(3) - INTERVAL 3 MINUTE""")
        expected = {f"quake-{r[0]}" for r in rows}
        have = {r[0] for r in ch("SELECT alert_id FROM du.alerts FINAL WHERE alert_type = 'quake_significant'")}
    except RuntimeError as exc:
        bad(f"查询失败：{exc}")
        return
    missing = expected - have
    if not expected:
        ok("近 20 小时没有 M4.5+ 地震，无需对账（等有地震后再跑一次更有说服力）")
        return
    check(not missing, f"M4.5+ 地震 {len(expected)} 个，缺告警 {len(missing)} 个 {sorted(missing)[:5]}")


SPIKE_SQL = """
SELECT region, toString(window_start) FROM (
  SELECT region, window_start, x,
         (s - x) / (n - 1) AS mean,
         sqrt(greatest((ss - x * x) / (n - 1) - pow((s - x) / (n - 1), 2), 0)) AS sd,
         greatest(sd, sqrt(greatest(mean, 0)), 1) AS sd_floor
  FROM (
    SELECT region, window_start, toFloat64(event_cnt) AS x,
           count() OVER w AS n,
           sum(toFloat64(event_cnt)) OVER w AS s,
           sum(toFloat64(event_cnt) * toFloat64(event_cnt)) OVER w AS ss
    FROM (
      SELECT region, window_start, event_cnt FROM du.agg_minute FINAL
      WHERE source = 'wiki' AND region != 'Unknown'
        AND window_start >= toDateTime({lo_base}, 'UTC') AND window_start <= toDateTime({hi}, 'UTC')
    )
    WINDOW w AS (PARTITION BY region ORDER BY toUInt32(window_start)
                 RANGE BETWEEN {window_s} PRECEDING AND CURRENT ROW)
  )
  WHERE n >= {n_min}
)
WHERE (x - mean) / sd_floor >= {z_min} AND x - mean >= {delta_min}
  AND window_start >= toDateTime({lo}, 'UTC')
"""


def check_spike_alerts() -> None:
    section("3b. 维基激增告警：Flink 结果 vs ClickHouse 独立重算")
    now = int(time.time())
    hi = now - now % 60 - 4 * 60  # 留出 W1 窗口关闭 + 30s watermark + 落库的时间
    lo = hi - 3 * 3600
    try:
        oldest = ch("SELECT toUInt32(min(window_start)) FROM du.agg_minute WHERE source = 'wiki'")[0][0]
        lo = max(lo, int(oldest) + WINDOW_S + 60)
        if hi - lo < 30 * 60:
            bad("维基分钟聚合不足 1 小时，基线不够：make up 后至少运行 40 分钟再验收")
            return
        expected = {
            (r[0], r[1])
            for r in ch(SPIKE_SQL.format(lo_base=lo - WINDOW_S - 60, hi=hi, lo=lo, window_s=WINDOW_S,
                                         n_min=BASELINE_MIN + 1, z_min=Z_MIN, delta_min=DELTA_MIN))
        }
        actual = {
            (r[0], r[1])
            for r in ch(f"""SELECT region, window_start FROM du.alerts FINAL
                WHERE alert_type = 'wiki_spike'
                  AND event_time >= toDateTime({lo}, 'UTC') AND event_time <= toDateTime({hi}, 'UTC')""")
        }
    except RuntimeError as exc:
        bad(f"查询失败：{exc}")
        return
    span = f"{time.strftime('%H:%M', time.gmtime(lo))}~{time.strftime('%H:%M', time.gmtime(hi))} UTC"
    union = expected | actual
    if not union:
        ok(f"{span} 内重算与 Flink 均无激增（一致）")
        return
    jac = len(expected & actual) / len(union)
    check(
        jac >= THRESHOLDS["spike_jaccard_min"],
        f"{span}：重算 {len(expected)} 条、Flink {len(actual)} 条，Jaccard {jac:.3f} ≥ {THRESHOLDS['spike_jaccard_min']}",
    )
    for tag, diff in (("仅重算有", expected - actual), ("仅 Flink 有", actual - expected)):
        if diff:
            info(f"{tag}：{sorted(diff)[:5]}")


# ---------------------------------------------------------------- 4. 网关
async def probe_ws_alerts() -> None:
    import websockets

    async with websockets.connect(WS_URL, max_size=None) as ws:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if m.get("t") == "alerts":
                check(isinstance(m.get("rows"), list), f"WebSocket 收到告警快照（{len(m['rows'])} 条）")
                for a in m["rows"]:
                    if a.get("lat") is None and a.get("alert_type") == "wiki_spike":
                        bad(f"维基告警没有补全坐标：{a.get('region')}")
                        break
                return
        bad("8 秒内没有收到 alerts 消息")


def check_gateway() -> None:
    section("4. 网关告警推送")
    try:
        _, m = http_json(f"{GATEWAY}/api/metrics")
        check(isinstance(m.get("alerts_24h"), dict), f"/api/metrics 含 alerts_24h：{m.get('alerts_24h')}")
        check(isinstance(m.get("alerts_1h"), int), "/api/metrics 含 alerts_1h")
        asyncio.run(probe_ws_alerts())
    except Exception as exc:  # noqa: BLE001
        bad(f"网关检查失败：{exc!r}")


# ---------------------------------------------------------------- 5. AI 提问
def check_ai() -> bool:
    section("5. AI 提问")
    _, st = http_json(f"{GATEWAY}/api/ask/status")
    if not st.get("enabled"):
        if os.getenv("VERIFY_SKIP_AI") == "1":
            info("AI 未开启，仓库所有者设置了 VERIFY_SKIP_AI=1，跳过（W3 DoD 未完全达成）")
            return False
        bad("AI 未开启：在 .env 设置 LLM_API_KEY 并 docker compose up -d gateway")
        return False
    ok(f"AI 已开启：{st.get('provider')} / {st.get('model')}")
    q = "过去一小时维基百科编辑最多的 3 个地区是哪些？各多少次？"
    t0 = time.monotonic()
    code, r = http_json(f"{GATEWAY}/api/ask", {"question": q}, timeout=60)
    dt = time.monotonic() - t0
    if code != 200:
        bad(f"/api/ask 返回 {code}：{r}")
        return True
    check(dt <= THRESHOLDS["ask_max_s"], f"回答耗时 {dt:.1f}s ≤ {THRESHOLDS['ask_max_s']}s")
    check(len(r.get("sql", [])) >= 1, f"执行了 {len(r.get('sql', []))} 条 SQL")
    check(bool(r.get("answer")), f"回答：{(r.get('answer') or '')[:80]}")
    check(len(r.get("highlights", [])) >= 1, f"地球高亮 {len(r.get('highlights', []))} 处")
    if r.get("sql"):
        try:  # 模型执行过的 SQL 用 du_ai 重放必须仍然可执行
            ch(r["sql"][-1], "du_ai", os.getenv("AI_CH_PASSWORD", "du_ai_dev"))
            ok("最后一条 SQL 可用 du_ai 重放")
        except RuntimeError as exc:
            bad(f"SQL 重放失败：{exc}")
    code, r = http_json(f"{GATEWAY}/api/ask", {"question": "x"})
    check(code == 422, f"过短问题被拒绝（{code}）")
    return True


# ---------------------------------------------------------------- 6. 回放
def load_gz(p: Path):
    return json.loads(gzip.decompress(p.read_bytes()))


def check_bundle(d: Path, min_minutes: int, min_qa: int, max_mb: float, label: str) -> dict:
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    minutes = (m["end_ms"] - m["start_ms"]) / 60_000
    check(minutes >= min_minutes, f"{label}：时长 {minutes:.0f} 分钟 ≥ {min_minutes}")
    check(len(m["chunks"]) == round(minutes), f"{label}：切片数 {len(m['chunks'])} = 分钟数")
    total = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
    check(total <= max_mb * 1e6, f"{label}：体积 {total / 1e6:.1f} MB ≤ {max_mb} MB")
    n_wiki = n_fl = 0
    bad_rows = 0
    for c in m["chunks"]:
        body = load_gz(d / c["file"])
        n_wiki += len(body["wiki"])
        n_fl += len(body["opensky"])
        bad_rows += sum(1 for r in body["wiki"] if len(r) != 9 or not (c["t0"] <= r[4] < c["t0"] + m["chunk_ms"]))
        bad_rows += sum(1 for r in body["opensky"] if len(r) != 10)
        ts = [r[4] for r in body["wiki"]]
        bad_rows += int(ts != sorted(ts))
    check(bad_rows == 0, f"{label}：切片行格式 / 时间范围 / 排序正确（异常 {bad_rows}）")
    check(n_wiki > 0 and n_fl > 0, f"{label}：维基 {n_wiki} 条、航班位置 {n_fl} 条")
    if min_qa:
        good = [q for q in m.get("qa", []) if q.get("answer") and q.get("sql")]
        check(len(good) >= min_qa, f"{label}：有效预置问答 {len(good)} 条 ≥ {min_qa}")
    return m


def check_replay(ai_on: bool) -> None:
    section("6. 回放")
    # 6a. 现场导出 10 分钟，与 ClickHouse 逐分钟对数
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [sys.executable, "-m", "gateway.replay_export", "--minutes", "10", "--out", tmp, "--no-qa"]
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            bad(f"导出失败：{(p.stdout + p.stderr)[-400:]}")
            return
        info(p.stdout.strip().splitlines()[-1])
        rid = json.loads((Path(tmp) / "index.json").read_text())["replays"][0]["id"]
        m = check_bundle(Path(tmp) / rid, 10, 0, THRESHOLDS["replay_max_mb"] / 6 + 1, "现场导出")
        cap = m["sampling"]["wiki_per_min"]
        exp = {
            int(r[0]): int(r[1])
            for r in ch(f"""SELECT toUnixTimestamp(toStartOfMinute(event_time)) * 1000, uniqExact(event_id)
                FROM du.events WHERE source = 'wiki' AND lat IS NOT NULL
                  AND event_time >= fromUnixTimestamp64Milli({m['start_ms']}, 'UTC')
                  AND event_time <  fromUnixTimestamp64Milli({m['end_ms']}, 'UTC')
                GROUP BY 1""")
        }
        worst = min(
            (c["n"]["wiki"] / min(cap, exp.get(c["t0"], 0)) if min(cap, exp.get(c["t0"], 0)) else 1.0)
            for c in m["chunks"]
        )
        check(0.98 <= worst <= 1.0 + 1e-9, f"每分钟维基条数 = min(上限 {cap}, ClickHouse 计数)，最差比值 {worst:.3f}")
    # 6b. 用于部署的演示回放
    root = ROOT / "web" / "public" / "replay"
    try:
        rid = json.loads((root / "index.json").read_text(encoding="utf-8"))["replays"][0]["id"]
    except (OSError, ValueError, IndexError, KeyError):
        bad("web/public/replay/index.json 不存在或为空：先 make replay-export")
        return
    check_bundle(
        root / rid,
        THRESHOLDS["replay_min_minutes"],
        THRESHOLDS["replay_min_qa"] if ai_on else 0,
        THRESHOLDS["replay_max_mb"],
        f"演示回放 {rid}",
    )


def main() -> int:
    check_infra()
    check_ai_account()
    check_quake_alerts()
    check_spike_alerts()
    check_gateway()
    ai_on = check_ai()
    check_replay(ai_on)
    print()
    if failed:
        print("\033[31mW3 验收未通过\033[0m")
        return 1
    print("\033[32mW3 验收全部通过\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
