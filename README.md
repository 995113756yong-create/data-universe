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
