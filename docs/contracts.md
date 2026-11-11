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


---

# W3 新增契约（只增不改，W1/W2 契约不变）

## alert.anomaly（Flink 作业 `data-universe-w3-alerts` 产出，JSON）
列顺序 = `streaming/flink-sql/30_alerts_ddl.sql` 的 `alert_anomaly` = ClickHouse `du.alerts_queue`（`tests/test_contracts.py` 校验）。

| 字段 | 类型 | wiki_spike | quake_significant |
|---|---|---|---|
| alert_id | string | `wiki_spike-<region>-<window_start>` | `quake-<event_id>` |
| alert_type | string | `wiki_spike` | `quake_significant` |
| source | string | wiki | usgs |
| region | string | 地区 | 地区（缺省 Unknown） |
| window_start | string | 分钟窗口起点 `yyyy-MM-dd HH:mm:ss` UTC | 发震时间（同格式） |
| event_time_ms | long | 窗口起点 | 发震时间 |
| detected_ms | long | Flink 处理时间 | Flink 处理时间 |
| value | double | 该分钟编辑数 | 震级 |
| baseline_mean / baseline_std / zscore | double / null | 基线均值 / 标准差 / z | null |
| severity | string | z ≥ 6 → high，否则 medium | ≥6.0 critical，≥5.0 high，否则 medium |
| lat / lng | double / null | null（网关按 `region_centroids.json` 补地区中心点） | 震中 |
| title | string | `Wikipedia edit spike: <region>` | USGS 标题 |

**判定规则（改阈值必须同时改 Flink SQL、`scripts/verify_w3.py`、本表，契约测试会检查三处一致）**
- 维基激增：只看 `agg.minute` 中 `source='wiki'`、`region<>'Unknown'` 的行。每个地区取当前分钟及之前 30 分钟（`RANGE INTERVAL '30' MINUTE PRECEDING`）的行，
  剔除当前值后得到基线；基线行数 ≥ 10；`std_floor = max(基线总体标准差, sqrt(基线均值), 1)`；
  **z = (当前 − 均值) / std_floor，z ≥ 3 且当前比均值多 ≥ 10 条**才告警。没有编辑的分钟在聚合里没有行，基线只算有行的分钟（两边口径一致）。
- 显著地震：`raw.usgs` 中 `mag ≥ 4.5`（**M4.5**）且有坐标。USGS 修订会产生同一 `alert_id` 的多条消息，下游去重取最新。
- at-least-once：同一 `alert_id` 可能重复，消费方必须按 `alert_id` 去重。

## ClickHouse（W3）
- `du.alerts`：ReplacingMergeTree(_inserted_at)，ORDER BY (alert_type, alert_id)，TTL 30 天；查询加 FINAL。迁移 003。
- 用户 `du_ai`（迁移 004）：账号级 `readonly = 2`、`max_execution_time ≤ 15`、`max_result_rows ≤ 1000`，
  只授予 `du.events`、`du.agg_minute`、`du.alerts` 的 SELECT。AI 生成的 SQL 只能用这个账号执行。

## WebSocket 协议 v1 增补（向后兼容：只新增消息类型，`v` 仍为 1）
| t | 时机 | 内容 |
|---|---|---|
| alerts | 所有 snapshot 之后一条 | `rows`：近 6 小时告警（≤50，新→旧），元素为告警对象 |
| alert | Kafka 收到告警时 | `alert`：告警对象；`new`：首次出现为 true，修订为 false |

告警对象 = 上面 alert.anomaly 的字段（`alert_id` … `title`），另加 `geo_precision`：`exact`（震中）| `approx`（地区中心点）| `none`（无法定位，lat/lng 为 null）。
`metrics` 消息新增 `alerts_1h`（int）、`alerts_24h`（`{alert_type: count}`）。

## HTTP API（W3）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/ask/status` | `{enabled, provider, model}`；未配置 `LLM_API_KEY` 时 enabled=false |
| POST | `/api/ask` | 请求 `{question}`（2~300 字）。响应 `{answer, highlights[], sql[], table, steps, elapsed_ms, model}` |

- `highlights[]`：`{lat, lng, label, geo_precision: exact|approx}`，最多 10 个。
- `table`：最后一次查询的 `{columns, rows(≤20), total}`，可为 null。
- 错误：422 参数不合法；429 限流（每 IP 每分钟 `AI_PER_MIN`、全站每天 `AI_PER_DAY`、并发上限 3）；503 未开启；502 模型调用失败。
- 浏览器仍然只访问网关；模型 API 只由网关调用，密钥不下发到前端。

## 回放包（`python -m gateway.replay_export` 产出，`web/src/replay/format.ts` 消费）
```
<root>/index.json                 {"replays": [{id, title, start_ms, end_ms, bytes}]}，按开始时间倒序
<root>/<id>/manifest.json         见下
<root>/<id>/chunks/NNNNN.json.gz  {"t0": ms, "wiki": [点行], "opensky": [航班行]}，行格式同 WebSocket，按 event_ms 升序
```
manifest：`v`=1、`protocol`=1、`id`（开始时间 `YYYYMMDD-HHMM` UTC）、`title`、`created_ms`、`start_ms`、`end_ms`（整分钟）、
`chunk_ms`=60000、`sampling`、`chunks[{i, t0, file, n}]`、`quakes`（开始前 24 小时到结束的地震点行）、
`alerts`（开始前 6 小时到结束的告警对象）、`agg`（`[分钟 ms, source, region, cnt]`，开始前 30 分钟起）、`qa`（预置问答，结构同 `/api/ask` 响应，另加 `question`、`asked_ms`）。
- 切片里维基行的 title / url 置空；第 0 片额外包含开始前 10 分钟的航班位置（预热）。
- `.json.gz` 由浏览器 `DecompressionStream` 解压；前端按 gzip 魔数判断，兼容托管方自动解压的情况。
