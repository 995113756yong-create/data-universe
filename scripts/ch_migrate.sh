#!/usr/bin/env bash
# 按文件名顺序执行 storage/clickhouse/migrations/*.sql。每个迁移文件必须幂等。
set -euo pipefail
cd "$(dirname "$0")/.."
for f in storage/clickhouse/migrations/*.sql; do
  echo "[migrate] $f"
  docker compose exec -T clickhouse clickhouse-client --user du --password du_dev --multiquery < "$f"
done
echo "[migrate] done"
