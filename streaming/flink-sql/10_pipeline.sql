-- 由 sql-client -f 加载。两条 INSERT 放进同一个 STATEMENT SET = 一个 Flink 作业，source 复用。
-- 字符串字面量一律 CAST AS STRING：UNION ALL 时 CHAR(n) 长度不同会被补空格。
EXECUTE STATEMENT SET
BEGIN

INSERT INTO evt_unified
SELECT
  event_id,
  CAST('usgs' AS STRING)                                AS source,
  COALESCE(quake_type, CAST('earthquake' AS STRING))    AS event_type,
  event_time_ms,
  ingest_time_ms,
  COALESCE(updated_ms, event_time_ms)                   AS version,
  lat,
  lng,
  CAST('exact' AS STRING)                               AS geo_precision,
  COALESCE(region, CAST('Unknown' AS STRING))           AS region,
  CAST(GREATEST(COALESCE(mag, 0.0), 0.0) AS DOUBLE)     AS weight,
  title,
  url,
  JSON_OBJECT('mag' VALUE mag, 'depth_km' VALUE depth_km, 'place' VALUE place) AS attrs
FROM raw_usgs
WHERE event_id IS NOT NULL AND event_time_ms IS NOT NULL
UNION ALL
SELECT
  event_id,
  CAST('wiki' AS STRING)                                AS source,
  change_type                                           AS event_type,
  event_time_ms,
  ingest_time_ms,
  event_time_ms                                         AS version,
  lat,
  lng,
  CAST('approx' AS STRING)                              AS geo_precision,
  COALESCE(region, CAST('Unknown' AS STRING))           AS region,
  CAST(ABS(COALESCE(bytes_delta, CAST(0 AS BIGINT))) AS DOUBLE) AS weight,
  title,
  url,
  JSON_OBJECT('wiki' VALUE wiki, 'lang' VALUE lang, 'bot' VALUE bot, 'namespace' VALUE `namespace`) AS attrs
FROM raw_wiki
WHERE event_id IS NOT NULL AND event_time_ms IS NOT NULL;

-- 1 分钟滚动窗口。COUNT(DISTINCT event_id) 吸收窗口内的重复/修订消息；
-- 窗口关闭后才到的修订消息属于迟到数据，被丢弃，不会重复计数。
INSERT INTO agg_minute
SELECT
  DATE_FORMAT(window_start, 'yyyy-MM-dd HH:mm:ss') AS ws,
  DATE_FORMAT(window_end, 'yyyy-MM-dd HH:mm:ss')   AS we,
  CAST('wiki' AS STRING)                           AS source,
  COALESCE(region, CAST('Unknown' AS STRING))      AS region,
  COUNT(DISTINCT event_id)                         AS event_cnt,
  CAST(SUM(ABS(COALESCE(bytes_delta, CAST(0 AS BIGINT)))) AS DOUBLE) AS weight_sum,
  CAST(MAX(ABS(COALESCE(bytes_delta, CAST(0 AS BIGINT)))) AS DOUBLE) AS weight_max
FROM TABLE(TUMBLE(TABLE raw_wiki, DESCRIPTOR(event_time), INTERVAL '1' MINUTE))
GROUP BY window_start, window_end, COALESCE(region, CAST('Unknown' AS STRING))
UNION ALL
SELECT
  DATE_FORMAT(window_start, 'yyyy-MM-dd HH:mm:ss') AS ws,
  DATE_FORMAT(window_end, 'yyyy-MM-dd HH:mm:ss')   AS we,
  CAST('usgs' AS STRING)                           AS source,
  COALESCE(region, CAST('Unknown' AS STRING))      AS region,
  COUNT(DISTINCT event_id)                         AS event_cnt,
  CAST(SUM(GREATEST(COALESCE(mag, 0.0), 0.0)) AS DOUBLE) AS weight_sum,
  CAST(MAX(GREATEST(COALESCE(mag, 0.0), 0.0)) AS DOUBLE) AS weight_max
FROM TABLE(TUMBLE(TABLE raw_usgs, DESCRIPTOR(event_time), INTERVAL '1' MINUTE))
GROUP BY window_start, window_end, COALESCE(region, CAST('Unknown' AS STRING));

END;
