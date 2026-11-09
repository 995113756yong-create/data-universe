# 数据契约（冻结，不得修改）

改动本文件内任何字段，需要作者本人确认，并同步修改 parser、Flink DDL、ClickHouse schema 和测试。

## Topic
| Topic | 生产者 | 消费者 | 分区 | 保留 | key |
|---|---|---|---|---|---|
| raw.usgs | collectors | Flink | 1 | 24h | event_id |
| raw.wiki | collectors | Flink | 1 | 24h | event_id |
| raw.opensky | （预留） | — | 1 | 6h | — |
| evt.unified | Flink | ClickHouse | 1 | 24h | 无 |
| agg.minute | Flink | ClickHouse | 1 | 72h | 无 |
| alert.anomaly | （预留 W3） | — | 1 | 72h | — |

## raw.usgs（字段顺序 = `RAW_USGS_FIELDS`）
| 字段 | 类型 | 来源 | 规则 |
|---|---|---|---|
| event_id | string | `id` | 必填 |
| quake_type | string | `properties.type` | 缺省 earthquake |
| mag | float/null | `properties.mag` | 可负、可空，原样保留 |
| place | string/null | `properties.place` | |
| region | string | place 推导 | 最后一个 `", "` 后的部分；美国州名/州代码→United States；MX→Mexico；空→Unknown |
| lat | float | `geometry.coordinates[1]` | 缺坐标整条丢弃 |
| lng | float | `geometry.coordinates[0]` | |
| depth_km | float/null | `geometry.coordinates[2]` | |
| event_time_ms | int | `properties.time` | |
| updated_ms | int | `properties.updated` | 缺省 = event_time_ms；作为版本号 |
| ingest_time_ms | int | 采集时刻 | |
| url | string | `properties.url` | 缺省 "" |
| title | string | `properties.title` | 缺省 "" |

采集端去重：同一 event_id 只有 updated_ms 变大才重发。

## raw.wiki（字段顺序 = `RAW_WIKI_FIELDS`）
| 字段 | 类型 | 来源 | 规则 |
|---|---|---|---|
| event_id | string | `meta.id` | |
| wiki | string | `wiki` | |
| lang | string | `server_name` 第一段 | |
| change_type | string | `type` | 仅 edit/new |
| namespace | int | `namespace` | |
| title | string | `title` | |
| bot | bool | `bot` | |
| bytes_delta | int/null | `length.new - length.old` | old 缺省 0；无 length 为 null |
| event_time_ms | int | `timestamp * 1000` | |
| ingest_time_ms | int | 采集时刻 | |
| url | string | `meta.uri` | |
| region | string | `lang_region.json` | 查不到 Unknown |
| lat / lng | float/null | `lang_region.json` | 查不到 null（近似坐标，geo_precision=approx） |

过滤顺序：`meta.domain == canary` → 非 `*.wikipedia.org` → 非 edit/new。**不输出 user 字段。**

## evt.unified
| 字段 | 类型 | usgs | wiki |
|---|---|---|---|
| event_id | string | event_id | event_id |
| source | string | usgs | wiki |
| event_type | string | quake_type | change_type |
| event_time_ms | bigint | event_time_ms | event_time_ms |
| ingest_time_ms | bigint | ingest_time_ms | ingest_time_ms |
| version | bigint | updated_ms | event_time_ms |
| lat / lng | double/null | lat / lng | lat / lng |
| geo_precision | string | exact | approx |
| region | string | region | region |
| weight | double | max(mag, 0) | abs(bytes_delta) |
| title / url | string | | |
| attrs | JSON string | mag, depth_km, place | wiki, lang, bot, namespace |

## agg.minute
| 字段 | 类型 | 说明 |
|---|---|---|
| window_start / window_end | string | `yyyy-MM-dd HH:mm:ss`，UTC |
| source | string | usgs / wiki |
| region | string | |
| event_cnt | bigint | COUNT(DISTINCT event_id) |
| weight_sum / weight_max | double | |

## ClickHouse
- `du.events`：ReplacingMergeTree(version)，ORDER BY (source, event_id)，TTL 7 天
- `du.agg_minute`：ReplacingMergeTree(_inserted_at)，ORDER BY (source, region, window_start)，TTL 30 天
- 两张表都通过 Kafka 引擎表 + 物化视图写入
