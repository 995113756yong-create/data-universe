-- 由 sql-client -f 加载。region 取 origin_country（注册国，不是飞机当前所在地，见 contracts.md）。
INSERT INTO evt_unified
SELECT
  event_id,
  CAST('opensky' AS STRING)                                   AS source,
  CAST('flight_pos' AS STRING)                                AS event_type,
  event_time_ms,
  ingest_time_ms,
  event_time_ms                                               AS version,
  lat,
  lng,
  CAST('exact' AS STRING)                                     AS geo_precision,
  COALESCE(origin_country, CAST('Unknown' AS STRING))         AS region,
  CAST(COALESCE(baro_altitude_m, geo_altitude_m, 0.0) AS DOUBLE) AS weight,
  CASE WHEN callsign IS NULL OR callsign = '' THEN icao24 ELSE callsign END AS title,
  CAST('' AS STRING)                                          AS url,
  JSON_OBJECT(
    'icao24' VALUE icao24,
    'callsign' VALUE callsign,
    'velocity_ms' VALUE velocity_ms,
    'heading_deg' VALUE heading_deg,
    'vertical_rate_ms' VALUE vertical_rate_ms,
    'geo_altitude_m' VALUE geo_altitude_m
  )                                                           AS attrs
FROM raw_opensky
WHERE event_id IS NOT NULL AND icao24 IS NOT NULL
  AND event_time_ms IS NOT NULL AND lat IS NOT NULL AND lng IS NOT NULL;
