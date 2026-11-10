#!/usr/bin/env bash
# W2：航班数据量大，缩短相关 topic 的保留时间（幂等，可重复执行）
set -euo pipefail
cd "$(dirname "$0")/.."
H=3600000
docker compose exec -T redpanda rpk topic alter-config evt.unified --set retention.ms=$((6 * H))
docker compose exec -T redpanda rpk topic alter-config raw.opensky --set retention.ms=$((3 * H))
docker compose exec -T redpanda rpk topic describe evt.unified -c | grep -E '^retention.ms' || true
