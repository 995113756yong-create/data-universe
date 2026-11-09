-- 首次启动时由 clickhouse 镜像自动执行（数据卷为空时才执行）。
-- 改了这个文件需要 `make clean && make up` 才会生效。
CREATE DATABASE IF NOT EXISTS du;

-- ===================== 统一事件 =====================
-- ReplacingMergeTree(version)：按 (source, event_id) 去重并保留最大 version，
-- 用来吸收 at-least-once 带来的重复和 USGS 修订。查询需要精确去重时加 FINAL。
CREATE TABLE IF NOT EXISTS du.events
(
    event_id      String,
    source        LowCardinality(String),
    event_type    LowCardinality(String),
    event_time    DateTime64(3, 'UTC'),
    ingest_time   DateTime64(3, 'UTC'),
    version       UInt64,
    lat           Nullable(Float64),
    lng           Nullable(Float64),
    geo_precision LowCardinality(String),
    region        LowCardinality(String),
    weight        Float32,
    title         String,
    url           String,
    attrs         String,
    _inserted_at  DateTime64(3, 'UTC') DEFAULT now64(3),
    INDEX idx_event_time event_time TYPE minmax GRANULARITY 1
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMMDD(event_time)
ORDER BY (source, event_id)
TTL toDateTime(event_time) + INTERVAL 7 DAY;

CREATE TABLE IF NOT EXISTS du.events_queue
(
    event_id       String,
    source         String,
    event_type     String,
    event_time_ms  Int64,
    ingest_time_ms Int64,
    version        UInt64,
    lat            Nullable(Float64),
    lng            Nullable(Float64),
    geo_precision  String,
    region         String,
    weight         Float64,
    title          String,
    url            String,
    attrs          String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list = 'evt.unified',
    kafka_group_name = 'ch_du_events',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_skip_broken_messages = 100,
    kafka_flush_interval_ms = 1000;   -- 默认 7.5s，会直接吃掉 <5s 的延迟预算

CREATE MATERIALIZED VIEW IF NOT EXISTS du.events_mv TO du.events AS
SELECT
    event_id,
    source,
    event_type,
    fromUnixTimestamp64Milli(event_time_ms, 'UTC')  AS event_time,
    fromUnixTimestamp64Milli(ingest_time_ms, 'UTC') AS ingest_time,
    version,
    lat,
    lng,
    geo_precision,
    region,
    toFloat32(weight) AS weight,
    title,
    url,
    attrs
FROM du.events_queue;

-- ===================== 1 分钟聚合 =====================
CREATE TABLE IF NOT EXISTS du.agg_minute
(
    window_start DateTime('UTC'),
    window_end   DateTime('UTC'),
    source       LowCardinality(String),
    region       LowCardinality(String),
    event_cnt    UInt64,
    weight_sum   Float64,
    weight_max   Float64,
    _inserted_at DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(_inserted_at)
PARTITION BY toYYYYMMDD(window_start)
ORDER BY (source, region, window_start)
TTL window_start + INTERVAL 30 DAY;

CREATE TABLE IF NOT EXISTS du.agg_minute_queue
(
    window_start String,
    window_end   String,
    source       String,
    region       String,
    event_cnt    UInt64,
    weight_sum   Float64,
    weight_max   Float64
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list = 'agg.minute',
    kafka_group_name = 'ch_du_agg_minute',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_skip_broken_messages = 100,
    kafka_flush_interval_ms = 1000;

CREATE MATERIALIZED VIEW IF NOT EXISTS du.agg_minute_mv TO du.agg_minute AS
SELECT
    toDateTime(window_start, 'UTC') AS window_start,
    toDateTime(window_end, 'UTC')   AS window_end,
    source,
    region,
    event_cnt,
    weight_sum,
    weight_max
FROM du.agg_minute_queue;
