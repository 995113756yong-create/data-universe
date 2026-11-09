#!/usr/bin/env bash
# W1 端到端验收。全部 PASS 才算 W1 完成。不允许为了通过而调低阈值。
# 前提：make up 之后至少运行 3 分钟（聚合窗口 + 30s watermark 需要时间产出）。
set -uo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose"
JOB_NAME="data-universe-w1"
FAILED=0

pass() { printf '\033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m  %s\n' "$1"; FAILED=1; }
ch()   { $COMPOSE exec -T clickhouse clickhouse-client --user du --password du_dev --database du --format TSV -q "$1" 2>&1; }
num_ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a+0 >= b+0) }'; }
num_le() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a+0 <= b+0) }'; }

echo "== 1. 容器状态"
for svc in redpanda console jobmanager taskmanager clickhouse collectors; do
  state=$($COMPOSE ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s {print $2}')
  [ "$state" = "running" ] && pass "$svc running" || fail "$svc state=${state:-missing}"
done

echo "== 2. Topic"
topics=$($COMPOSE exec -T redpanda rpk topic list 2>/dev/null | awk 'NR>1 {print $1}')
for t in raw.usgs raw.wiki raw.opensky evt.unified agg.minute alert.anomaly; do
  grep -qx "$t" <<<"$topics" && pass "topic $t" || fail "topic $t missing"
done

echo "== 3. Flink 作业"
running=$($COMPOSE exec -T jobmanager ./bin/flink list -r 2>/dev/null | grep -c ": $JOB_NAME (RUNNING)" || true)
[ "$running" = "1" ] && pass "flink job RUNNING (exactly 1)" || fail "flink RUNNING 实例数=$running，期望 1"

echo "== 4. ClickHouse 入库"
wiki_10m=$(ch "SELECT count() FROM events WHERE source='wiki' AND _inserted_at > now64(3) - INTERVAL 10 MINUTE")
num_ge "$wiki_10m" 300 && pass "wiki 近 10 分钟入库 $wiki_10m 行 (>=300)" || fail "wiki 近 10 分钟入库 $wiki_10m 行 (<300)"
usgs_total=$(ch "SELECT count() FROM events WHERE source='usgs'")
num_ge "$usgs_total" 1 && pass "usgs 已入库 $usgs_total 行" || fail "usgs 无数据（USGS 每小时通常有多条，检查采集器日志）"

echo "== 5. 延迟（采集 -> ClickHouse 落表）"
p95=$(ch "SELECT toUInt64(quantile(0.95)(toUnixTimestamp64Milli(_inserted_at) - toUnixTimestamp64Milli(ingest_time))) FROM events WHERE source='wiki' AND _inserted_at > now64(3) - INTERVAL 5 MINUTE")
num_le "$p95" 5000 && pass "wiki p95 管道延迟 ${p95}ms (<=5000)" || fail "wiki p95 管道延迟 ${p95}ms (>5000)"

echo "== 6. 去重"
dup=$(ch "SELECT count() - uniqExact(event_id) FROM events FINAL WHERE source='usgs'")
[ "$dup" = "0" ] && pass "usgs FINAL 后无重复" || fail "usgs FINAL 后仍有 $dup 条重复"

echo "== 7. 聚合"
agg_rows=$(ch "SELECT count() FROM agg_minute WHERE source='wiki' AND window_start > now() - INTERVAL 10 MINUTE")
num_ge "$agg_rows" 1 && pass "wiki 近 10 分钟聚合 $agg_rows 行" || fail "wiki 近 10 分钟无聚合结果"
ratio=$(ch "
  SELECT round(sum(a.cnt) / greatest(sum(e.cnt), 1), 3)
  FROM (SELECT window_start AS ws, sum(event_cnt) AS cnt FROM agg_minute FINAL
        WHERE source='wiki' AND window_start BETWEEN now() - INTERVAL 8 MINUTE AND now() - INTERVAL 3 MINUTE
        GROUP BY ws) AS a
  INNER JOIN
       (SELECT toDateTime(toStartOfMinute(event_time), 'UTC') AS ws, uniqExact(event_id) AS cnt FROM events
        WHERE source='wiki' AND event_time >= now() - INTERVAL 9 MINUTE
        GROUP BY ws) AS e
  USING ws")
num_ge "$ratio" 0.95 && num_le "$ratio" 1.05 \
  && pass "聚合/明细一致性 ratio=$ratio (0.95~1.05)" \
  || fail "聚合/明细一致性 ratio=$ratio，超出 0.95~1.05"

echo
if [ "$FAILED" = "0" ]; then echo "W1 验收全部通过"; exit 0; else echo "存在 FAIL，见上方"; exit 1; fi
