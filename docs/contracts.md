# 数据契约（冻结，不得修改）

改动本文件内任何字段，需要作者本人确认，并同步修改 parser、Flink DDL、ClickHouse schema 和测试。

## Topic
| Topic | 生产者 | 消费者 | 分区 | 保留 | key |
|---|---|---|---|---|---|
| raw.usgs | collectors | Flink | 1 | 24h | event_id |
| raw.wiki | collectors | Flink | 1 | 24h | event_id |
| raw.opensky | collectors | Flink（W2 作业） | 1 | 3h（W2 由 `scripts/w2_topics.sh` 调整） | event_id |
| evt.unified | Flink（W1 + W2 两个作业） | ClickHouse、网关 | 1 | 6h（W2 调整，原 24h） | 无 |
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

## raw.opensky（W2，字段顺序 = `RAW_OPENSKY_FIELDS`）
来源：OpenSky `GET /api/states/all` 的 state vector（下标见 `collectors/opensky/parser.py` 顶部注释）。

| 字段 | 类型 | 来源下标 | 规则 |
|---|---|---|---|
| event_id | string | — | `{icao24}-{time_position}` |
| icao24 | string | 0 | 去空格、小写 |
| callsign | string | 1 | 去补齐空格；缺省 "" |
| origin_country | string | 2 | 飞机**注册国**，不是当前所在地；缺省 Unknown |
| lat / lng | float | 6 / 5 | 注意下标 5 是经度、6 是纬度 |
| baro_altitude_m | float/null | 7 | |
| geo_altitude_m | float/null | 13 | |
| velocity_ms | float/null | 9 | 地速 m/s |
| heading_deg | float/null | 10 | true_track，正北为 0 顺时针 |
| vertical_rate_ms | float/null | 11 | |
| event_time_ms | int | 3 | time_position × 1000 |
| last_contact_ms | int | 4 | × 1000；缺省 = event_time_ms |
| ingest_time_ms | int | 采集时刻 | |

过滤：字段不足 / 无 icao24 / 无 time_position / 无坐标 / `on_ground=true` / 位置比响应时间早 60 秒以上 / 坐标越界。
采集端去重：同一 icao24 的 time_position 没变就不重发。

## evt.unified
| 字段 | 类型 | usgs | wiki | opensky（W2） |
|---|---|---|---|---|
| event_id | string | event_id | event_id | event_id |
| source | string | usgs | wiki | opensky |
| event_type | string | quake_type | change_type | flight_pos |
| event_time_ms | bigint | event_time_ms | event_time_ms | event_time_ms |
| ingest_time_ms | bigint | ingest_time_ms | ingest_time_ms | ingest_time_ms |
| version | bigint | updated_ms | event_time_ms | event_time_ms |
| lat / lng | double/null | lat / lng | lat / lng | lat / lng |
| geo_precision | string | exact | approx | exact |
| region | string | region | region | origin_country |
| weight | double | max(mag, 0) | abs(bytes_delta) | 高度 m（baro，缺省 geo，再缺省 0） |
| title | string | title | title | callsign，空则 icao24 |
| url | string | url | url | "" |
| attrs | JSON string | mag, depth_km, place | wiki, lang, bot, namespace | icao24, callsign, velocity_ms, heading_deg, vertical_rate_ms, geo_altitude_m |

W1 作业（`00_ddl.sql`）与 W2 航班作业（`20_opensky_ddl.sql`）中 `evt_unified` 的定义必须逐列一致，由 `tests/test_contracts.py` 校验。

## agg.minute
| 字段 | 类型 | 说明 |
|---|---|---|
| window_start / window_end | string | `yyyy-MM-dd HH:mm:ss`，UTC |
| source | string | usgs / wiki |
| region | string | |
| event_cnt | bigint | COUNT(DISTINCT event_id) |
| weight_sum / weight_max | double | |

## ClickHouse
- `du.events`：ReplacingMergeTree(version)，ORDER BY (source, event_id)，TTL 7 天；W2 迁移 002 后 opensky 只保留 1 天
- `du.agg_minute`：ReplacingMergeTree(_inserted_at)，ORDER BY (source, region, window_start)，TTL 30 天
- 两张表都通过 Kafka 引擎表 + 物化视图写入

- schema 变更只通过 `storage/clickhouse/migrations/NNN_xxx.sql`（幂等），由 `make ch-migrate` 执行

## WebSocket 协议 v1（网关 ⇄ 浏览器，W2）
地址 `ws://<host>:8090/ws`。所有消息都是 JSON，`t` 字段区分类型。行数据用数组（不用对象），列顺序即契约，
定义在 `gateway/src/gateway/protocol.py`（`POINT_FIELDS` / `FLIGHT_FIELDS`）与 `web/src/protocol.ts`，两边必须一致。

**点行（wiki / usgs，9 列）**：`[id, lat, lng, weight, event_ms, ingest_ms, region, title, url]`

**航班行（opensky，10 列）**：`[icao24, lat, lng, heading_deg|null, velocity_ms|null, altitude_m, event_ms, ingest_ms, callsign, origin_country]`

### 服务端 → 浏览器
| t | 时机 | 内容 |
|---|---|---|
| hello | 连接后第一条 | `v`=1, `server_ms`, `tick_ms`, `layers` |
| snapshot | hello 之后，每个图层一条 | `layer`, `rows`：wiki 近 120 秒（≤3000）、usgs 近 24 小时（≤2000）、opensky 每架飞机最新位置（近 FLIGHT_WINDOW_S 秒） |
| batch | 每 tick（默认 200ms），无数据不发 | `rows`（按图层分组）、`dropped`（本包被抽样丢弃数）、`cap`、`pending`、`server_ms` |
| metrics | 每 2 秒 | eps、last_minute、lag_ms、flights_tracked、sources、trend、top_regions、quakes_24h 等 |
| warn | 快照失败等 | `msg` |

### 浏览器 → 服务端
| t | 内容 |
|---|---|
| subscribe | `layers`: 要接收的图层列表 |
| load | `fps`: 浏览器当前帧率，网关据此调整 wiki 推送上限（背压） |

### 推送策略（不得改成无上限）
| 图层 | 策略 |
|---|---|
| wiki | 每 tick 最多 `cap` 条（默认 200，背压时最低 20），超出蓄水池抽样，丢弃数写进 `dropped` |
| usgs | 全部推送（安全上限 5000） |
| opensky | 按 icao24 合并只留最新位置，每 tick 最多 2500 条，剩余留到下个 tick |
