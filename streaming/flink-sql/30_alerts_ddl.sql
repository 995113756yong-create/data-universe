-- W3 异常告警作业（独立作业，不改动 W1/W2 作业拓扑）。由 sql-client -i 加载。
-- alert_anomaly 的列必须与 storage/clickhouse/migrations/003_w3_alerts.sql 的 du.alerts_queue 一致（tests/test_contracts.py 校验）
SET 'pipeline.name' = 'data-universe-w3-alerts';
SET 'table.local-time-zone' = 'UTC';
SET 'table.exec.source.idle-timeout' = '30 s';
SET 'execution.checkpointing.interval' = '30 s';

-- 分钟聚合（W1 作业产出）。wiki 每个窗口关闭后一次性写出，单分区内按时间有序，
-- 所以 watermark 只留 30 秒：下一分钟的数据一到，上一分钟就能出结果（告警延迟约 1~2 分钟）。
-- usgs 的聚合晚约 20 分钟，会被当作迟到数据——本作业只用 wiki 的聚合，不受影响。
CREATE TABLE agg_minute_src (
  window_start    STRING,
  window_end      STRING,
  source          STRING,
  region          STRING,
  event_cnt       BIGINT,
  weight_sum      DOUBLE,
  weight_max      DOUBLE,
  ts AS TO_TIMESTAMP(window_start, 'yyyy-MM-dd HH:mm:ss'),
  WATERMARK FOR ts AS ts - INTERVAL '30' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'agg.minute',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'properties.group.id' = 'flink-du-w3-alerts',
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true'
);

-- 地震原始流（只做过滤，不需要 watermark）
CREATE TABLE raw_usgs_src (
  event_id        STRING,
  quake_type      STRING,
  mag             DOUBLE,
  place           STRING,
  region          STRING,
  lat             DOUBLE,
  lng             DOUBLE,
  depth_km        DOUBLE,
  event_time_ms   BIGINT,
  updated_ms      BIGINT,
  ingest_time_ms  BIGINT,
  url             STRING,
  title           STRING
) WITH (
  'connector' = 'kafka',
  'topic' = 'raw.usgs',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'properties.group.id' = 'flink-du-w3-alerts',
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true'
);

CREATE TABLE alert_anomaly (
  alert_id        STRING,
  alert_type      STRING,
  source          STRING,
  region          STRING,
  window_start    STRING,
  event_time_ms   BIGINT,
  detected_ms     BIGINT,
  `value`         DOUBLE,
  baseline_mean   DOUBLE,
  baseline_std    DOUBLE,
  zscore          DOUBLE,
  severity        STRING,
  lat             DOUBLE,
  lng             DOUBLE,
  title           STRING
) WITH (
  'connector' = 'kafka',
  'topic' = 'alert.anomaly',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'format' = 'json',
  'sink.delivery-guarantee' = 'at-least-once'
);

-- 每个地区：当前分钟 + 过去 30 分钟的计数、和、平方和。
-- RANGE 窗口包含当前行，基线要把当前值剔除（见 31_alerts_pipeline.sql）
CREATE TEMPORARY VIEW wiki_minute_stats AS
SELECT
  region,
  window_start,
  CAST(event_cnt AS DOUBLE) AS x,
  COUNT(*) OVER w AS n,
  SUM(CAST(event_cnt AS DOUBLE)) OVER w AS s,
  SUM(CAST(event_cnt AS DOUBLE) * CAST(event_cnt AS DOUBLE)) OVER w AS ss
FROM agg_minute_src
WHERE source = 'wiki' AND region IS NOT NULL AND region <> 'Unknown' AND event_cnt IS NOT NULL
WINDOW w AS (
  PARTITION BY region
  ORDER BY ts
  RANGE BETWEEN INTERVAL '30' MINUTE PRECEDING AND CURRENT ROW
);

CREATE TEMPORARY VIEW wiki_minute_z AS
SELECT
  region,
  window_start,
  x,
  n - 1 AS baseline_n,
  (s - x) / (n - 1) AS mean,
  -- 样本标准差下限取 sqrt(mean)（计数近似泊松分布）和 1，避免平稳地区出现极小方差导致 z 虚高
  GREATEST(
    SQRT(GREATEST((ss - x * x) / (n - 1) - POWER((s - x) / (n - 1), 2), CAST(0 AS DOUBLE))),
    SQRT(GREATEST((s - x) / (n - 1), CAST(0 AS DOUBLE))),
    CAST(1 AS DOUBLE)
  ) AS std_floor,
  SQRT(GREATEST((ss - x * x) / (n - 1) - POWER((s - x) / (n - 1), 2), CAST(0 AS DOUBLE))) AS std
FROM wiki_minute_stats
WHERE n >= 11;
