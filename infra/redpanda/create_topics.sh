#!/usr/bin/env bash
# 幂等创建 topic：已存在则跳过。全部 1 分区（避免多分区空闲导致 Flink watermark 卡住）。
set -euo pipefail
BROKERS="${BROKERS:-redpanda:9092}"

existing="$(rpk topic list -X brokers="$BROKERS" | awk 'NR>1 {print $1}')"

create() {
  local name="$1" retention_ms="$2"
  if grep -qx "$name" <<<"$existing"; then
    echo "[skip] $name already exists"
  else
    rpk topic create "$name" -p 1 -r 1 -c retention.ms="$retention_ms" -X brokers="$BROKERS"
  fi
}

H=3600000
create raw.usgs      $((24 * H))
create raw.wiki      $((24 * H))
create raw.opensky   $((6 * H))
create evt.unified   $((24 * H))
create agg.minute    $((72 * H))
create alert.anomaly $((72 * H))

rpk topic list -X brokers="$BROKERS"
exit 0
