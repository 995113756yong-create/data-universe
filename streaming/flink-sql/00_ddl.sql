-- 由 sql-client -i 加载：只允许 SET 与 DDL。契约见 docs/contracts.md
SET 'pipeline.name' = 'data-universe-w1';
SET 'table.local-time-zone' = 'UTC';
SET 'table.exec.source.idle-timeout' = '30 s';
SET 'execution.checkpointing.interval' = '30 s';

-- ===================== Sources =====================
CREATE TABLE raw_usgs (
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
  title           STRING,
  -- COALESCE 兜底：时间缺失的脏数据落到 1970 年，窗口里视为迟到被丢弃，不会让作业因空 rowtime 失败
  event_time AS TO_TIMESTAMP_LTZ(COALESCE(event_time_ms, CAST(0 AS BIGINT)), 3),
  -- USGS 存在数分钟到十几分钟的上报延迟，容忍 20 分钟乱序（代价：地震窗口结果晚 20 分钟产出）
  WATERMARK FOR event_time AS event_time - INTERVAL '20' MINUTE
) WITH (
  'connector' = 'kafka',
  'topic' = 'raw.usgs',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'properties.group.id' = 'flink-du-w1',
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true'
);

CREATE TABLE raw_wiki (
  event_id        STRING,
  wiki            STRING,
  lang            STRING,
  change_type     STRING,
  `namespace`     INT,
  title           STRING,
  bot             BOOLEAN,
  bytes_delta     BIGINT,
  event_time_ms   BIGINT,
  ingest_time_ms  BIGINT,
  url             STRING,
  region          STRING,
  lat             DOUBLE,
  lng             DOUBLE,
  event_time AS TO_TIMESTAMP_LTZ(COALESCE(event_time_ms, CAST(0 AS BIGINT)), 3),
  WATERMARK FOR event_time AS event_time - INTERVAL '30' SECOND
) WITH (
  'connector' = 'kafka',
  'topic' = 'raw.wiki',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'properties.group.id' = 'flink-du-w1',
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true'
);

-- ===================== Sinks =====================
CREATE TABLE evt_unified (
  event_id        STRING,
  source          STRING,
  event_type      STRING,
  event_time_ms   BIGINT,
  ingest_time_ms  BIGINT,
  version         BIGINT,
  lat             DOUBLE,
  lng             DOUBLE,
  geo_precision   STRING,
  region          STRING,
  weight          DOUBLE,
  title           STRING,
  url             STRING,
  attrs           STRING
) WITH (
  'connector' = 'kafka',
  'topic' = 'evt.unified',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'format' = 'json',
  'sink.delivery-guarantee' = 'at-least-once'
);

CREATE TABLE agg_minute (
  window_start    STRING,   -- 'yyyy-MM-dd HH:mm:ss'，UTC
  window_end      STRING,
  source          STRING,
  region          STRING,
  event_cnt       BIGINT,
  weight_sum      DOUBLE,
  weight_max      DOUBLE
) WITH (
  'connector' = 'kafka',
  'topic' = 'agg.minute',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'format' = 'json',
  'sink.delivery-guarantee' = 'at-least-once'
);
