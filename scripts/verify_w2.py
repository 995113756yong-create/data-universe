#!/usr/bin/env python3
r"""W2 端到端验收。全部 PASS 才算 W2 完成。不允许调低阈值、删检查项。

前提：make up 之后至少运行 5 分钟，且前端已 make web-build。
运行：gateway/.venv/bin/python scripts/verify_w2.py   （Windows: gateway\.venv\Scripts\python.exe）
依赖：仅标准库 + websockets（gateway 的 dev 依赖）。
"""

from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

GATEWAY = "http://localhost:8090"
WS_URL = "ws://localhost:8090/ws"
OS_JOB = "data-universe-w2-opensky"
ROOT = Path(__file__).resolve().parents[1]

THRESHOLDS = {
    "first_paint_s": 1.0,  # 连接 -> 收到非空维基快照
    # 合包节拍：按服务端 server_ms 计算，batch 间隔偏离 tick 整数倍的 p95。
    # 协议规定无数据的 tick 不发 batch，间隔天然是 tick 的整数倍（数据稀疏时 400/600ms 都正常），
    # 所以不能用间隔中位数衡量；事件循环被阻塞、发送变慢错过 tick 时，偏差会直接体现出来。
    "tick_offset_p95_ms": 30,
    "browser_lag_p95_ms": 2000,  # 采集 -> 浏览器（维基）
    "flights_min": 500,
    "wiki_eps_min": 1.0,
    "consistency": (0.95, 1.05),  # 网关按分钟计数 / ClickHouse
}

failed = False


def ok(msg: str) -> None:
    print(f"\033[32mPASS\033[0m  {msg}")


def bad(msg: str) -> None:
    global failed
    failed = True
    print(f"\033[31mFAIL\033[0m  {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else bad)(msg)


def http_json(path: str):
    with urllib.request.urlopen(GATEWAY + path, timeout=10) as r:
        return json.loads(r.read())


def compose(*args: str) -> str:
    out = subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    return out.stdout + out.stderr


def ch(sql: str) -> str:
    return compose(
        "exec", "-T", "clickhouse", "clickhouse-client", "--user", "du", "--password", "du_dev",
        "--database", "du", "--format", "TSV", "-q", sql,
    ).strip()


def section(title: str) -> None:
    print(f"== {title}")


def check_infra() -> None:
    section("1. W2 组件")
    jobs = compose("exec", "-T", "jobmanager", "./bin/flink", "list", "-r")
    check(jobs.count(f": {OS_JOB} (RUNNING)") == 1, f"Flink 作业 {OS_JOB} RUNNING（恰好 1 个）")
    check(jobs.count(": data-universe-w1 (RUNNING)") == 1, "W1 作业仍在运行（恰好 1 个）")
    ttl = ch("SELECT engine_full FROM system.tables WHERE database='du' AND name='events'")
    ttl = ttl.replace("\\'", "'")  # TSV 输出会把单引号转义成 \'
    check(
        "source = 'opensky'" in ttl and "toIntervalDay(1)" in ttl,
        "ClickHouse 迁移 002 已生效（opensky TTL 1 天）",
    )
    n = ch("SELECT count() FROM events WHERE source='opensky' AND _inserted_at > now64(3) - INTERVAL 30 MINUTE")
    check(n.isdigit() and int(n) >= THRESHOLDS["flights_min"], f"opensky 近 30 分钟入库 {n} 行 (>= {THRESHOLDS['flights_min']})")
    bad_rows = ch("SELECT count() FROM events WHERE source='opensky' AND (lat IS NULL OR abs(lat) > 90 OR abs(lng) > 180)")
    check(bad_rows == "0", f"opensky 坐标合法（异常 {bad_rows} 行）")


def check_gateway() -> None:
    section("2. 网关 HTTP")
    try:
        h = http_json("/healthz")
    except Exception as exc:  # noqa: BLE001
        bad(f"/healthz 不可达: {exc!r}")
        return
    check(h.get("kafka_ok") is True, f"网关已连上 Kafka (consumed={h.get('consumed')})")
    m = http_json("/api/metrics")
    check(m.get("clickhouse_ok") is True, "网关查询 ClickHouse 正常")
    check(m["eps"]["wiki"] >= THRESHOLDS["wiki_eps_min"], f"wiki eps={m['eps']['wiki']} (>= {THRESHOLDS['wiki_eps_min']})")
    check(m["flights_tracked"] >= THRESHOLDS["flights_min"], f"在空航班 {m['flights_tracked']} (>= {THRESHOLDS['flights_min']})")
    check(m["sources"]["wiki"]["status"] == "ok", f"wiki 数据源状态 {m['sources']['wiki']['status']}")
    check(m["sources"]["opensky"]["status"] == "ok", f"opensky 数据源状态 {m['sources']['opensky']['status']}")
    check(len(m.get("trend") or []) >= 5, f"趋势数据 {len(m.get('trend') or [])} 个点 (>= 5)")
    with urllib.request.urlopen(GATEWAY + "/", timeout=10) as r:
        html = r.read().decode("utf-8", "replace")
    check(r.status == 200 and "Data Universe" in html, "前端页面由网关提供（GET / 200）")

    section("3. 面板数据与 ClickHouse 对数")
    mc = http_json("/api/debug/minute_counts?source=wiki")
    gw = {int(k): v for k, v in mc["gateway"].items()}
    chc = {int(k): v for k, v in mc["clickhouse"].items()}
    now_min = int(time.time()) // 60 * 60000
    # 网关从最新位点开始消费：启动所在分钟及之前的分钟都不完整，排除；最近 2 分钟可能还在写入，也排除
    start_min = int(mc["started_ms"]) // 60000 * 60000
    minutes = sorted(k for k in gw if start_min < k <= now_min - 120_000 and k in chc)
    if len(minutes) < 2:
        bad(f"可对比的完整分钟只有 {len(minutes)} 个，网关至少要运行 5 分钟后再验收")
    else:
        g, c = sum(gw[k] for k in minutes), sum(chc[k] for k in minutes)
        ratio = g / max(c, 1)
        lo, hi = THRESHOLDS["consistency"]
        check(lo <= ratio <= hi, f"{len(minutes)} 个分钟 网关 {g} / ClickHouse {c} = {ratio:.3f} ({lo}~{hi})")


async def probe_ws() -> None:
    section("4. WebSocket 探针（15 秒）")
    import websockets

    t0 = time.monotonic()
    got = {"hello": None, "snap": {}, "first_paint": None}
    ticks: list[float] = []
    lags: list[int] = []
    shape_ok = True
    metrics_seen = False
    async with websockets.connect(WS_URL, max_size=32 * 1024 * 1024) as ws:
        end = t0 + 15
        while time.monotonic() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=end - time.monotonic())
            except TimeoutError:
                break
            now_ms = time.time_ns() // 1_000_000
            m = json.loads(raw)
            t = m.get("t")
            if t == "hello":
                got["hello"] = m
            elif t == "snapshot":
                got["snap"][m["layer"]] = len(m["rows"])
                if m["layer"] == "wiki" and m["rows"] and got["first_paint"] is None:
                    got["first_paint"] = time.monotonic() - t0
            elif t == "batch":
                ticks.append(m["server_ms"])
                for row in m["rows"].get("wiki", []):
                    shape_ok &= len(row) == 9
                    lags.append(now_ms - row[5])
                for row in m["rows"].get("opensky", []):
                    shape_ok &= len(row) == 10
                if m["rows"].get("wiki") and got["first_paint"] is None:
                    got["first_paint"] = time.monotonic() - t0
            elif t == "metrics":
                metrics_seen = True

    h = got["hello"]
    check(bool(h) and h.get("v") == 1, "收到 hello，协议版本 1")
    check(set(got["snap"]) == {"wiki", "usgs", "opensky"}, f"三个图层快照 {got['snap']}")
    fp = got["first_paint"]
    check(fp is not None and fp <= THRESHOLDS["first_paint_s"], f"首屏有点耗时 {fp if fp is None else round(fp, 3)}s (<= {THRESHOLDS['first_paint_s']})")
    check(metrics_seen, "收到 metrics 推送")
    check(shape_ok, "batch 行字段数符合契约（点 9 列 / 航班 10 列）")
    if len(ticks) >= 10:
        tick_ms = (h or {}).get("tick_ms") or 200
        iv = [b - a for a, b in zip(ticks, ticks[1:], strict=False)]
        off = sorted(abs(x - round(x / tick_ms) * tick_ms) for x in iv)
        p95 = off[int(len(off) * 0.95) - 1 if len(off) > 1 else 0]
        lim = THRESHOLDS["tick_offset_p95_ms"]
        check(
            min(iv) >= tick_ms - lim and p95 <= lim,
            f"合包节拍：{len(ticks)} 个 batch，间隔偏离 {tick_ms}ms 整数倍 p95 {p95}ms (<= {lim})，"
            f"最小间隔 {min(iv)}ms，中位 {statistics.median(iv):.0f}ms（数据稀疏时为整数倍属正常）",
        )
    else:
        bad(f"15 秒只收到 {len(ticks)} 个 batch")
    if lags:
        lags.sort()
        p95 = lags[int(len(lags) * 0.95) - 1 if len(lags) > 1 else 0]
        check(p95 <= THRESHOLDS["browser_lag_p95_ms"], f"采集 -> 客户端 p95 {p95}ms (<= {THRESHOLDS['browser_lag_p95_ms']}, n={len(lags)})")
    else:
        bad("15 秒内没有收到任何维基点")


def main() -> int:
    check_infra()
    check_gateway()
    try:
        asyncio.run(probe_ws())
    except Exception as exc:  # noqa: BLE001
        bad(f"WebSocket 探针异常: {exc!r}")
    print()
    print("W2 验收全部通过" if not failed else "存在 FAIL，见上方")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
