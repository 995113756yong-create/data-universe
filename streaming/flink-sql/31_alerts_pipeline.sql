-- 由 sql-client -f 加载。阈值是契约的一部分（docs/contracts.md「alert.anomaly」），
-- scripts/verify_w3.py 用 ClickHouse SQL 独立重算一遍做对账，改这里必须同步改那里。
EXECUTE STATEMENT SET
BEGIN

-- 维基编辑激增：至少 10 分钟基线，z >= 3 且比基线多 10 条以上
INSERT INTO alert_anomaly
SELECT
  CONCAT('wiki_spike-', region, '-', window_start)                      AS alert_id,
  CAST('wiki_spike' AS STRING)                                          AS alert_type,
  CAST('wiki' AS STRING)                                                AS source,
  region,
  window_start,
  UNIX_TIMESTAMP(window_start, 'yyyy-MM-dd HH:mm:ss') * 1000            AS event_time_ms,
  UNIX_TIMESTAMP() * 1000                                               AS detected_ms,
  x                                                                     AS `value`,
  mean                                                                  AS baseline_mean,
  std                                                                   AS baseline_std,
  (x - mean) / std_floor                                                AS zscore,
  CASE WHEN (x - mean) / std_floor >= 6 THEN CAST('high' AS STRING)
       ELSE CAST('medium' AS STRING) END                                AS severity,
  CAST(NULL AS DOUBLE)                                                  AS lat,
  CAST(NULL AS DOUBLE)                                                  AS lng,
  CONCAT('Wikipedia edit spike: ', region)                              AS title
FROM wiki_minute_z
WHERE (x - mean) / std_floor >= 3 AND x - mean >= 10;

-- 显著地震：M4.5 及以上。USGS 修订会重复产生同一 alert_id，下游按 alert_id 去重取最新
INSERT INTO alert_anomaly
SELECT
  CONCAT('quake-', event_id)                                            AS alert_id,
  CAST('quake_significant' AS STRING)                                   AS alert_type,
  CAST('usgs' AS STRING)                                                AS source,
  COALESCE(region, CAST('Unknown' AS STRING))                           AS region,
  FROM_UNIXTIME(event_time_ms / 1000, 'yyyy-MM-dd HH:mm:ss')      AS window_start,
  event_time_ms,
  UNIX_TIMESTAMP() * 1000                                               AS detected_ms,
  mag                                                                   AS `value`,
  CAST(NULL AS DOUBLE)                                                  AS baseline_mean,
  CAST(NULL AS DOUBLE)                                                  AS baseline_std,
  CAST(NULL AS DOUBLE)                                                  AS zscore,
  CASE WHEN mag >= 6.0 THEN CAST('critical' AS STRING)
       WHEN mag >= 5.0 THEN CAST('high' AS STRING)
       ELSE CAST('medium' AS STRING) END                                AS severity,
  lat,
  lng,
  COALESCE(title, CAST('' AS STRING))                                   AS title
FROM raw_usgs_src
WHERE event_id IS NOT NULL AND event_time_ms IS NOT NULL
  AND mag IS NOT NULL AND mag >= 4.5
  AND lat IS NOT NULL AND lng IS NOT NULL;

END;
