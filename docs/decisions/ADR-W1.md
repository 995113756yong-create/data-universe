# W1 架构决策记录

## ADR-001 消息队列用 Redpanda
- **决策**：使用 Redpanda 单节点（兼容 Kafka API）。
- **原因**：单个二进制，不需要 ZooKeeper/KRaft 配置，本地 Docker 资源占用小；客户端和 Flink connector 都按 Kafka 协议使用，以后切换 Kafka 不需要改代码。

## ADR-002 append + version，下游幂等，而不是 Flink upsert
- **决策**：`evt.unified` 只追加写，每条带 `version`；ClickHouse 用 `ReplacingMergeTree(version)` 去重。
- **原因**：Flink 端「保留最新」去重会产生回撤流，要用 upsert-kafka，还要处理 tombstone，ClickHouse Kafka 引擎处理 null value 也很麻烦。端到端 at-least-once 加下游幂等，实现简单、可解释，效果上接近 exactly-once。
- **代价**：查询需要精确去重时要加 `FINAL`，或者用 `argMax`。

## ADR-003 维基地理映射放在采集端
- **决策**：语言 → 地区的近似映射在采集器里完成（`lang_region.json`）。
- **原因**：Flink SQL 做静态维表关联需要额外的 lookup connector，收益很小。映射是静态的、和数据源强相关，放在边缘更简单。
- **说明**：坐标是近似值，`geo_precision = approx`，展示时必须注明。

## ADR-004 传输统一用 epoch 毫秒
- **决策**：所有 topic 的时间字段都用 UTC epoch ms（Int64），只在 ClickHouse 落表时转成 DateTime64。
- **原因**：避免 Flink JSON 时间格式、ClickHouse 解析格式和时区三方不一致。聚合窗口边界用 `yyyy-MM-dd HH:mm:ss` 字符串，Flink 会话时区固定为 UTC。

## ADR-005 按数据源分别设置 watermark
- **决策**：wiki 30 秒，usgs 20 分钟；窗口聚合直接读两个 raw topic，而不是读混合后的 `evt.unified`。
- **原因**：两个源延迟差异很大。混在一个流里，watermark 会被 wiki 推进，导致 usgs 迟到数据被大量丢弃。
- **代价**：地震的分钟聚合要晚约 20 分钟产出；历史准确数据以 ClickHouse 明细为准。

## 已知限制
- 不带 savepoint 重启 Flink 时，正在计算中的窗口状态会丢失，可能写出偏小的计数并覆盖正确值。所以运维统一用 `make flink-stop` / `make flink-resume`。
- `ReplacingMergeTree` 只在同一分区内去重；如果 USGS 修订后发震时间跨了天，可能残留一条旧版本（概率极低）。
