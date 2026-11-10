-- W3：异常告警表。幂等（IF NOT EXISTS）。由 make ch-migrate 执行。
-- ReplacingMergeTree(_inserted_at)：同一 alert_id（at-least-once 重复、USGS 修订）保留最后写入的版本，查询精确去重加 FINAL
CREATE TABLE IF NOT EXISTS du.alerts
(
    alert_id      String,
    alert_type    LowCardinality(String),
    source        LowCardinality(String),
    region        LowCardinality(String),
    window_start  String,
    event_time    DateTime64(3, 'UTC'),
    detected_time DateTime64(3, 'UTC'),
    value         Float64,
    baseline_mean Nullable(Float64),
    baseline_std  Nullable(Float64),
    zscore        Nullable(Float64),
    severity      LowCardinality(String),
    lat           Nullable(Float64),
    lng           Nullable(Float64),
    title         String,
    _inserted_at  DateTime64(3, 'UTC') DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(_inserted_at)
PARTITION BY toYYYYMM(event_time)
ORDER BY (alert_type, alert_id)
TTL toDateTime(event_time) + INTERVAL 30 DAY;

CREATE TABLE IF NOT EXISTS du.alerts_queue
(
    alert_id       String,
    alert_type     String,
    source         String,
    region         String,
    window_start   String,
    event_time_ms  Int64,
    detected_ms    Int64,
    value          Float64,
    baseline_mean  Nullable(Float64),
    baseline_std   Nullable(Float64),
    zscore         Nullable(Float64),
    severity       String,
    lat            Nullable(Float64),
    lng            Nullable(Float64),
    title          String
)
ENGINE = Kafka
SETTINGS
    kafka_broker_list = 'redpanda:9092',
    kafka_topic_list = 'alert.anomaly',
    kafka_group_name = 'ch_du_alerts',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1,
    kafka_skip_broken_messages = 100,
    kafka_flush_interval_ms = 1000;

CREATE MATERIALIZED VIEW IF NOT EXISTS du.alerts_mv TO du.alerts AS
SELECT
    alert_id,
    alert_type,
    source,
    region,
    window_start,
    fromUnixTimestamp64Milli(event_time_ms, 'UTC') AS event_time,
    fromUnixTimestamp64Milli(detected_ms, 'UTC')   AS detected_time,
    value,
    baseline_mean,
    baseline_std,
    zscore,
    severity,
    lat,
    lng,
    title
FROM du.alerts_queue;
