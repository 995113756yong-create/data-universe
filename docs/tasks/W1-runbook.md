# W1 执行手册（Agent 逐步执行）

> 先读 `AGENTS.md`。每一步都要：执行 → 跑验收 → 通过后 commit → 下一步。
> 验收不过就查本步骤的排错表；表里没有的情况，按 AGENTS.md 的格式停下来报告。

## 环境要求
Docker Desktop / Docker Engine 24+（含 compose v2）、内存可分配 ≥ 6GB、Python 3.11、make、curl、可访问外网（Docker Hub、Maven Central、earthquake.usgs.gov、stream.wikimedia.org）。

---

## R0 初始化
```bash
git init && git add -A && git commit -m "chore: import W1 skeleton"
cp .env.example .env
```
**人工操作**：把 `.env` 里的 `HTTP_USER_AGENT` 改成真实 GitHub 地址和邮箱。Agent 不得代填。

**验收**：`grep -c '<' .env` 输出 `0`；`git status` 中没有 `.env`。

---

## R1 本地静态检查与单元测试
```bash
make dev-setup
make check
```
**验收**：ruff 无报错；pytest 全部通过（当前为 40 个用例）；输出 `compose config ok` 和 `shell syntax ok`。

| 现象 | 处理 |
|---|---|
| `python3.11` 不存在 | 安装 Python 3.11+，不要改 `requires-python` |
| ruff 格式问题 | `make fmt` 后重跑，只允许格式变化 |
| 测试失败 | 视为真实 bug：分析原因并报告，**不得改测试** |

---

## R2 启动基础设施（不含采集器）
```bash
docker compose up -d --build redpanda redpanda-init console jobmanager taskmanager clickhouse
docker compose ps
```
**验收**（全部满足）：
- `redpanda`、`clickhouse` 显示 healthy；`redpanda-init` 显示 `exited (0)`
- `make topics` 列出 6 个 topic
- `curl -s localhost:8081/overview` 中 `"taskmanagers":1`
- `docker compose exec -T clickhouse clickhouse-client --user du --password du_dev -q "SHOW TABLES FROM du"` 列出 `agg_minute agg_minute_mv agg_minute_queue events events_mv events_queue`

| 现象 | 处理 |
|---|---|
| 镜像 tag 拉不到 | 按白名单换同大版本 tag |
| Flink 镜像构建时 jar 下载 404 | 到 Maven Central 找 `flink-sql-connector-kafka` 的 `x.y.z-1.18` 版本替换 |
| taskmanager 反复重启 / OOM | Docker 内存调到 ≥ 6GB，不要改 compose 里的内存参数 |
| ClickHouse 表缺失 | `docker compose logs clickhouse` 查 init 报错；修 `001_schema.sql` 后 `make clean` 再启动 |
| ClickHouse 报权限 / 认证错误 | 确认用了 `--user du --password du_dev` |

---

## R3 启动采集器
```bash
docker compose up -d --build collectors
sleep 60
docker compose logs --tail=50 collectors
docker compose exec -T redpanda rpk topic consume raw.wiki -n 3
docker compose exec -T redpanda rpk topic consume raw.usgs -n 1
```
**验收**：
- 日志有 `kafka producer started` 和 `wiki stream connected`，30 秒一次的指标日志中 wiki `rate_per_s > 5`
- 消费到的消息字段与 `docs/contracts.md` 完全一致，wiki 消息里**没有 user 字段**

| 现象 | 处理 |
|---|---|
| `[config error] HTTP_USER_AGENT ...` | 回到 R0 让人改 .env |
| wiki 403 / 429 | UA 不合规或请求太频繁：检查 UA；不要伪装浏览器 UA |
| wiki 一直 ConnectTimeout | 网络访问不到 stream.wikimedia.org，报告人工处理（可能需要代理） |
| usgs 没有消息 | 正常情况下每小时有多条；等 2 分钟再看，日志有 HTTP 错误再报告 |

---

## R4 提交 Flink 作业
```bash
make flink-submit
make flink-status
```
**验收**：
- `make flink-status` 输出包含 `data-universe-w1 (RUNNING)`
- 打开 http://localhost:8081 → 作业 → Checkpoints，2 分钟内至少 2 次 COMPLETED，没有 FAILED
- 再执行一次 `make flink-submit`，提示「已在运行，跳过提交」（验证幂等）
- `docker compose exec -T redpanda rpk topic consume evt.unified -n 2` 有数据

| 现象 | 处理 |
|---|---|
| `Could not find any factory for identifier 'kafka'` | connector jar 没放进 `/opt/flink/lib` 或权限不对，检查 Dockerfile 的 chmod，重新 build |
| SQL 解析报错 | 原样报告报错和行号，不要自行改写 SQL 逻辑 |
| 作业反复重启 | Flink UI → Exceptions 复制完整堆栈并报告 |
| agg 一直不出 | 正常：wiki 窗口要等约 1.5 分钟，usgs 窗口要等 20 分钟以上（watermark 设计如此） |

---

## R5 ClickHouse 入库检查
等待 3 分钟后执行：
```bash
docker compose exec -T clickhouse clickhouse-client --user du --password du_dev --database du -q "
SELECT source, count(), max(event_time), max(_inserted_at) FROM events GROUP BY source"
```
**验收**：wiki 和 usgs 都有数据，`max(_inserted_at)` 距今不超过 10 秒。

| 现象 | 处理 |
|---|---|
| events 为空但 evt.unified 有数据 | 查 `system.kafka_consumers` 的 last_exception（见 `scripts/verify.sql`） |
| 时间差 8 小时 | 时区问题：全链路应为 UTC，报告具体字段 |

---

## R6 端到端验收
```bash
make verify
```
**验收**：全部 PASS，最后一行为 `W1 验收全部通过`。任何 FAIL 都按 AGENTS.md 格式报告，**不允许改阈值**。

---

## R7 健壮性测试
```bash
# 7.1 采集器重启：数据继续流入
docker compose restart collectors && sleep 90 && make verify

# 7.2 Flink 带 savepoint 停止再恢复
make flink-stop                      # 记下输出里的 savepoint 路径
make flink-resume SAVEPOINT=<上一步的路径>
sleep 120 && make verify

# 7.3 全量重启
make down && make up && sleep 180 && make verify
```
**验收**：三次 `make verify` 全部通过；usgs 去重检查仍为 0。

---

## R8 收尾
- README 补充：启动步骤、各服务端口、`make verify` 结果截图位置（`docs/assets/`）
- `git log --oneline` 每个步骤至少一个 commit
- 最后提交：`docs: W1 pipeline verified`

## 完成定义（DoD）
- [ ] `make check` 全绿
- [ ] `make verify` 全绿（R6、R7 各轮）
- [ ] 没有违反 AGENTS.md 的任何禁止项（`git diff` 自查：tests/、contracts.md、verify.sh 阈值没有被改动）
