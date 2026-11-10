# 🌍 Data Universe

> Watch the world happen — in real time.

实时汇聚 USGS 地震和 Wikipedia 编辑数据流，经 **Redpanda → Flink SQL → ClickHouse** 处理，后续渲染到 3D 地球上。

**当前进度：W1 数据链路**

## 快速开始
```bash
cp .env.example .env      # 修改 HTTP_USER_AGENT 为你的联系方式
make up                   # 启动全链路并提交 Flink 作业
# 等 3 分钟
make verify               # 端到端验收
```

| 服务 | 地址 |
|---|---|
| Redpanda Console | http://localhost:8080 |
| Flink UI | http://localhost:8081 |
| ClickHouse HTTP | http://localhost:8123（du / du_dev） |

验收结果留档：[docs/assets/verify-w1.txt](docs/assets/verify-w1.txt)（`make verify` 全 16 项 PASS）。
逐步执行手册见 [docs/tasks/W1-runbook.md](docs/tasks/W1-runbook.md)。

### Windows 环境注意
`make` 的 recipe 在原生 Windows 下会因路径转换与引号处理出错，建议改用 Git Bash 执行等价命令：

```bash
export MSYS_NO_PATHCONV=1
export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"
bash scripts/verify.sh                                   # 代替 make verify
docker compose exec -T jobmanager ./bin/sql-client.sh \
  -i /opt/flink/sql/00_ddl.sql -f /opt/flink/sql/10_pipeline.sql   # 代替 make flink-submit
```

`make check` 需为 venv 补 `bin` → `Scripts` 链接（`.venv` 已在 `.gitignore` 内）：
```powershell
New-Item -ItemType Junction -Path collectors\.venv\bin -Target collectors\.venv\Scripts
```

## 架构
```
USGS / Wikipedia ─► collectors (Python asyncio)
                 ─► Redpanda  raw.usgs / raw.wiki
                 ─► Flink SQL  统一事件模型 + 1 分钟窗口聚合
                 ─► Redpanda  evt.unified / agg.minute
                 ─► ClickHouse Kafka 引擎 + 物化视图 + ReplacingMergeTree
```
- 数据契约：[docs/contracts.md](docs/contracts.md)
- 架构决策：[docs/decisions/ADR-W1.md](docs/decisions/ADR-W1.md)

> 说明：维基编辑没有真实坐标，按语言站点映射到近似地区（`geo_precision = approx`）。
