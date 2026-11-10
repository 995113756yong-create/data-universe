-- W2 航班作业（独立作业，不改动 W1 作业的拓扑，W1 的 savepoint 仍然可用）
-- 由 sql-client -i 加载。evt_unified 的定义必须与 00_ddl.sql 完全一致（tests/test_contracts.py 会校验）。
SET 'pipeline.name' = 'data-universe-w2-opensky';
SET 'table.local-time-zone' = 'UTC';
SET 'execution.checkpointing.interval' = '30 s';

-- 无窗口计算，不需要 watermark
CREATE TABLE raw_opensky (
  event_id          STRING,
  icao24            STRING,
  callsign          STRING,
  origin_country    STRING,
  lat               DOUBLE,
  lng               DOUBLE,
  baro_altitude_m   DOUBLE,
  geo_altitude_m    DOUBLE,
  velocity_ms       DOUBLE,
  heading_deg       DOUBLE,
  vertical_rate_ms  DOUBLE,
  event_time_ms     BIGINT,
  last_contact_ms   BIGINT,
  ingest_time_ms    BIGINT
) WITH (
  'connector' = 'kafka',
  'topic' = 'raw.opensky',
  'properties.bootstrap.servers' = 'redpanda:9092',
  'properties.group.id' = 'flink-du-w2-opensky',
  'scan.startup.mode' = 'group-offsets',
  'properties.auto.offset.reset' = 'earliest',
  'format' = 'json',
  'json.ignore-parse-errors' = 'true'
);

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
