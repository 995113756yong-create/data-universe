-- 手工排查用查询（make ch 进入客户端后粘贴）

-- 各数据源入库概况
SELECT source, count() AS rows, uniqExact(event_id) AS ids, max(event_time) AS latest_event, max(_inserted_at) AS latest_insert
FROM du.events GROUP BY source;

-- 管道延迟分位数（ms）
SELECT source,
       quantiles(0.5, 0.95, 0.99)(toUnixTimestamp64Milli(_inserted_at) - toUnixTimestamp64Milli(ingest_time)) AS pipeline_ms,
       quantiles(0.5, 0.95)(toUnixTimestamp64Milli(ingest_time) - toUnixTimestamp64Milli(event_time)) AS source_lag_ms
FROM du.events WHERE _inserted_at > now64(3) - INTERVAL 10 MINUTE GROUP BY source;

-- 最近 10 分钟 Top 地区
SELECT source, region, sum(event_cnt) AS cnt
FROM du.agg_minute FINAL WHERE window_start > now() - INTERVAL 10 MINUTE
GROUP BY source, region ORDER BY cnt DESC LIMIT 20;

-- Kafka 引擎消费异常（24.x 起可用）
SELECT table, last_exception, last_exception_time, num_messages_read
FROM system.kafka_consumers WHERE database = 'du';
