"""把 ClickHouse 里一段时间的数据导出成静态回放包（GitHub Pages / 任意静态托管直接可用）。

用法（宿主机，全链路运行中）：
    gateway/.venv/bin/python -m gateway.replay_export --minutes 60 --out web/public/replay

产物（契约见 docs/contracts.md「回放包」）：
    <out>/index.json                     回放列表，最新在前
    <out>/<id>/manifest.json             元信息、地震、告警、分钟聚合、预置问答
    <out>/<id>/chunks/00000.json.gz      每分钟一个切片
                                         {"t0", "wiki": [PointRow], "opensky": [FlightRow]}
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import orjson

from gateway.alerts import ALERT_FIELDS, load_centroids, normalize
from gateway.protocol import PROTOCOL_VERSION, encode

MANIFEST_VERSION = 1
CHUNK_MS = 60_000
FLIGHT_PREROLL_MS = 10 * 60_000  # 回放开始时已在空中的飞机：取开始前 10 分钟的位置放进第一个切片
MAX_MINUTES = 360
DEFAULT_QUESTIONS = (
    "过去一小时维基百科编辑最多的 5 个地区是哪些？",
    "过去 24 小时最强的地震发生在哪里？震级多少？",
    "最近一小时有哪些异常告警？",
    "现在空中大约有多少架航班？注册国最多的是哪几个？",
    "日本过去一小时的维基编辑量和前一小时相比怎么样？",
)

EVENT_COLS = """event_id, source, lat, lng, weight,
    toUnixTimestamp64Milli(event_time) AS event_time_ms,
    toUnixTimestamp64Milli(ingest_time) AS ingest_time_ms,
    region, title, url, attrs"""
EVENT_KEYS = (
    "event_id",
    "source",
    "lat",
    "lng",
    "weight",
    "event_time_ms",
    "ingest_time_ms",
    "region",
    "title",
    "url",
    "attrs",
)

SQL_WIKI = f"""
SELECT {EVENT_COLS} FROM (
    SELECT * FROM du.events
    WHERE source = 'wiki' AND lat IS NOT NULL
      AND event_time >= fromUnixTimestamp64Milli({{s:Int64}}, 'UTC')
      AND event_time <  fromUnixTimestamp64Milli({{e:Int64}}, 'UTC')
    LIMIT 1 BY event_id
)
ORDER BY toStartOfMinute(event_time), cityHash64(event_id)
LIMIT {{cap:UInt32}} BY toStartOfMinute(event_time)
"""

# 航班：按 icao24 哈希抽样一部分飞机（同一架飞机始终在或不在样本里），每架每 step 秒保留一个位置
SQL_FLIGHTS = f"""
SELECT {EVENT_COLS} FROM (
    SELECT *, JSONExtractString(attrs, 'icao24') AS icao,
           intDiv(toUnixTimestamp(event_time), {{step:UInt32}}) AS bucket
    FROM du.events
    WHERE source = 'opensky' AND lat IS NOT NULL
      AND event_time >= fromUnixTimestamp64Milli({{s:Int64}}, 'UTC')
      AND event_time <  fromUnixTimestamp64Milli({{e:Int64}}, 'UTC')
      AND cityHash64(JSONExtractString(attrs, 'icao24')) % 1000 < {{permille:UInt32}}
    ORDER BY event_time DESC
    LIMIT 1 BY icao, bucket
)
ORDER BY event_time_ms
"""

SQL_QUAKES = f"""
SELECT {EVENT_COLS} FROM du.events FINAL
WHERE source = 'usgs'
  AND event_time >= fromUnixTimestamp64Milli({{s:Int64}}, 'UTC')
  AND event_time <  fromUnixTimestamp64Milli({{e:Int64}}, 'UTC')
ORDER BY event_time
"""

SQL_ALERTS = """
SELECT alert_id, alert_type, source, region, window_start,
       toUnixTimestamp64Milli(event_time), toUnixTimestamp64Milli(detected_time),
       value, baseline_mean, baseline_std, zscore, severity, lat, lng, title
FROM du.alerts FINAL
WHERE event_time >= fromUnixTimestamp64Milli({s:Int64}, 'UTC')
  AND event_time <  fromUnixTimestamp64Milli({e:Int64}, 'UTC')
ORDER BY event_time
"""

SQL_AGG = """
SELECT toUnixTimestamp(window_start) * 1000 AS ts, source, region, sum(event_cnt) AS cnt
FROM du.agg_minute FINAL
WHERE source IN ('wiki', 'usgs')
  AND window_start >= toDateTime(intDiv({s:Int64}, 1000), 'UTC')
  AND window_start <  toDateTime(intDiv({e:Int64}, 1000), 'UTC')
GROUP BY ts, source, region
ORDER BY ts
"""


# ---------------- 纯逻辑（单测覆盖） ----------------
def encode_events(raw_rows: list[list]) -> dict[str, list]:
    """ClickHouse 行 -> 按图层分组的协议行，按 event_id / icao24+时间去重。"""
    out: dict[str, list] = {"wiki": [], "usgs": [], "opensky": []}
    seen: set[tuple[str, str]] = set()
    for r in raw_rows:
        evt = dict(zip(EVENT_KEYS, r, strict=True))
        enc = encode(evt)
        if enc is None:
            continue
        layer, key, row = enc
        uid = (layer, evt["event_id"])
        if uid in seen:
            continue
        seen.add(uid)
        if layer == "wiki":
            row[7], row[8] = "", ""  # 回放不需要维基标题和链接，省体积
        out[layer].append(row)
    return out


def event_ms(layer: str, row: list) -> int:
    return row[6] if layer == "opensky" else row[4]


def build_chunks(layers: dict[str, list], start_ms: int, end_ms: int) -> list[dict]:
    """按分钟切片。早于 start 的航班位置（预热）归入第 0 片；超出范围的丢弃。每片内按时间排序。"""
    n = max(1, -(-(end_ms - start_ms) // CHUNK_MS))
    chunks = [{"t0": start_ms + i * CHUNK_MS, "wiki": [], "opensky": []} for i in range(n)]
    for layer in ("wiki", "opensky"):
        for row in layers.get(layer, []):
            t = event_ms(layer, row)
            if t >= end_ms:
                continue
            if t < start_ms:
                if layer != "opensky" or t < start_ms - FLIGHT_PREROLL_MS:
                    continue
                i = 0
            else:
                i = (t - start_ms) // CHUNK_MS
            chunks[i][layer].append(row)
    for c in chunks:
        for layer in ("wiki", "opensky"):
            c[layer].sort(key=lambda r, ly=layer: event_ms(ly, r))
    return chunks


def gz_json(obj) -> bytes:
    return gzip.compress(orjson.dumps(obj), compresslevel=9, mtime=0)


def write_bundle(out_root: Path, rid: str, manifest: dict, chunks: list[dict]) -> int:
    """写回放包，返回总字节数。"""
    d = out_root / rid
    (d / "chunks").mkdir(parents=True, exist_ok=True)
    total = 0
    entries = []
    for i, c in enumerate(chunks):
        data = gz_json(c)
        name = f"chunks/{i:05d}.json.gz"
        (d / name).write_bytes(data)
        total += len(data)
        entries.append(
            {
                "i": i,
                "t0": c["t0"],
                "file": name,
                "n": {"wiki": len(c["wiki"]), "opensky": len(c["opensky"])},
            }
        )
    manifest = {**manifest, "chunks": entries}
    body = orjson.dumps(manifest)
    (d / "manifest.json").write_bytes(body)
    total += len(body)
    return total


def update_index(out_root: Path, entry: dict, keep: int = 5) -> list[dict]:
    p = out_root / "index.json"
    try:
        items = json.loads(p.read_text(encoding="utf-8")).get("replays", [])
    except (OSError, ValueError):
        items = []
    items = [e for e in items if e.get("id") != entry["id"]]
    items.insert(0, entry)
    items.sort(key=lambda e: e.get("start_ms", 0), reverse=True)
    items = items[:keep]
    p.write_text(
        json.dumps({"replays": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return items


def parse_end(value: str, now_ms: int) -> int:
    """'now' -> 当前时间往前 2 分钟（等迟到数据落库）并对齐到分钟；否则解析 UTC 时间。"""
    if value == "now":
        t = now_ms - 2 * 60_000
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        t = int(dt.timestamp() * 1000)
    return t - t % CHUNK_MS


# ---------------- IO ----------------
class CH:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.c = httpx.Client(
            base_url=url,
            timeout=httpx.Timeout(120.0),
            headers={"X-ClickHouse-User": user, "X-ClickHouse-Key": password},
        )

    def rows(self, sql: str, **params) -> list[list]:
        q = {"database": "du", "default_format": "JSONCompact"}
        q.update({f"param_{k}": str(v) for k, v in params.items()})
        r = self.c.post("/", params=q, content=sql.encode())
        if r.status_code >= 400:
            raise RuntimeError(f"ClickHouse {r.status_code}: {r.text[:500]}")
        return orjson.loads(r.content)["data"]


def ask_presets(gateway: str, questions: list[str]) -> list[dict]:
    try:
        st = httpx.get(f"{gateway}/api/ask/status", timeout=5).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"[qa] 网关不可用，跳过预置问答：{exc!r}")
        return []
    if not st.get("enabled"):
        print("[qa] 网关未开启 AI（LLM_API_KEY 为空），跳过预置问答")
        return []
    out = []
    for q in questions:
        for attempt in range(3):
            r = httpx.post(f"{gateway}/api/ask", json={"question": q}, timeout=90)
            if r.status_code == 429:  # 每分钟限流
                time.sleep(15 * (attempt + 1))
                continue
            break
        if r.status_code != 200:
            print(f"[qa] 失败 {r.status_code}: {q} -> {r.text[:200]}")
            continue
        res = r.json()
        out.append({"question": q, "asked_ms": int(time.time() * 1000), **res})
        print(f"[qa] ok ({res.get('elapsed_ms')} ms): {q}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="导出 Data Universe 回放包")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--end", default="now", help="结束时间（UTC，ISO 格式）或 now")
    ap.add_argument("--out", default="web/public/replay")
    ap.add_argument("--title", default="")
    ap.add_argument("--ch-url", default="http://localhost:8123")
    ap.add_argument("--ch-user", default="du")
    ap.add_argument("--ch-password", default="du_dev")
    ap.add_argument("--wiki-per-min", type=int, default=1200)
    ap.add_argument("--flight-permille", type=int, default=400, help="抽样飞机比例（千分比）")
    ap.add_argument("--flight-step-s", type=int, default=120)
    ap.add_argument("--gateway", default="http://localhost:8090", help="用于生成预置问答")
    ap.add_argument("--no-qa", action="store_true")
    ap.add_argument("--questions", help="预置问题文件，每行一个")
    ap.add_argument("--budget-mb", type=float, default=30.0)
    ap.add_argument("--keep", type=int, default=5)
    a = ap.parse_args(argv)

    if not 5 <= a.minutes <= MAX_MINUTES:
        ap.error(f"--minutes 必须在 5~{MAX_MINUTES}")
    if not 1 <= a.flight_permille <= 1000:
        ap.error("--flight-permille 必须在 1~1000")
    now_ms = int(time.time() * 1000)
    end_ms = parse_end(a.end, now_ms)
    start_ms = end_ms - a.minutes * 60_000
    if now_ms - start_ms > 23 * 3600_000:
        print("[warn] 航班明细只保留 1 天，开始时间早于 23 小时前，航班可能不完整")
    rid = datetime.fromtimestamp(start_ms / 1000, UTC).strftime("%Y%m%d-%H%M")
    ch = CH(a.ch_url, a.ch_user, a.ch_password)
    t0 = time.time()

    raw = ch.rows(SQL_WIKI, s=start_ms, e=end_ms, cap=a.wiki_per_min)
    raw += ch.rows(
        SQL_FLIGHTS,
        s=start_ms - FLIGHT_PREROLL_MS,
        e=end_ms,
        step=a.flight_step_s,
        permille=a.flight_permille,
    )
    layers = encode_events(raw)
    quakes = encode_events(ch.rows(SQL_QUAKES, s=start_ms - 24 * 3600_000, e=end_ms))["usgs"]
    cent = load_centroids()
    try:
        alert_rows = ch.rows(SQL_ALERTS, s=start_ms - 6 * 3600_000, e=end_ms)
    except RuntimeError as exc:
        print(f"[warn] 读取告警失败（迁移 003 是否已执行？）：{exc}")
        alert_rows = []
    alerts = [
        a2
        for a2 in (normalize(dict(zip(ALERT_FIELDS, r, strict=True)), cent) for r in alert_rows)
        if a2
    ]
    agg = [
        [int(ts), src, reg, int(c)]
        for ts, src, reg, c in ch.rows(SQL_AGG, s=start_ms - 30 * 60_000, e=end_ms)
    ]
    chunks = build_chunks(layers, start_ms, end_ms)

    qa: list[dict] = []
    if not a.no_qa:
        qs = list(DEFAULT_QUESTIONS)
        if a.questions:
            qs = [
                ln.strip()
                for ln in Path(a.questions).read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
        qa = ask_presets(a.gateway.rstrip("/"), qs)

    title = a.title or datetime.fromtimestamp(start_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")
    manifest = {
        "v": MANIFEST_VERSION,
        "protocol": PROTOCOL_VERSION,
        "id": rid,
        "title": title,
        "created_ms": now_ms,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "chunk_ms": CHUNK_MS,
        "sampling": {
            "wiki_per_min": a.wiki_per_min,
            "flight_permille": a.flight_permille,
            "flight_step_s": a.flight_step_s,
        },
        "quakes": quakes,
        "alerts": alerts,
        "agg": agg,
        "qa": qa,
    }
    out_root = Path(a.out)
    total = write_bundle(out_root, rid, manifest, chunks)
    update_index(
        out_root,
        {"id": rid, "title": title, "start_ms": start_ms, "end_ms": end_ms, "bytes": total},
        keep=a.keep,
    )
    n_wiki = sum(len(c["wiki"]) for c in chunks)
    n_fl = sum(len(c["opensky"]) for c in chunks)
    print(
        f"[replay] {rid}: {len(chunks)} 个切片, wiki {n_wiki}, 航班位置 {n_fl}, "
        f"地震 {len(quakes)}, 告警 {len(alerts)}, 问答 {len(qa)}, "
        f"共 {total / 1e6:.1f} MB, 用时 {time.time() - t0:.1f}s"
    )
    if total > a.budget_mb * 1e6:
        print(
            f"[replay] 超出体积预算 {a.budget_mb} MB："
            "调小 --minutes / --flight-permille / --wiki-per-min",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
