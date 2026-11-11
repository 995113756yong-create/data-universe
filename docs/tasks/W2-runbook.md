# W2 执行手册（Agent 逐步执行）

> 先读 `AGENTS.md`（已更新到 W2）。每一步都要：执行 → 跑验收 → 通过后 commit → 下一步。
> 验收不过就查本步骤的排错表；表里没有的情况，按 AGENTS.md 的格式停下来报告。

**W2 目标**：三条数据流（维基 / 地震 / 航班）实时显示在 3D 地球上，右侧指标面板，2 万点 60fps，录出第一版 GIF。

**环境**：W1 的全部要求 + Node.js 20+。Windows 下 Makefile 有引号和路径改写问题，**强烈建议在 WSL2 的 Ubuntu 里执行**；
继续用 Git Bash 的话，每条 `docker compose exec` 前加 `MSYS_NO_PATHCONV=1`，`.venv/bin/` 换成 `.venv/Scripts/`。

**作者已验证的部分**：OpenSky 采集器用真实接口跑通；collectors 57 个、gateway 26 个、契约 5 个测试通过；compose / CI YAML 和 shell 语法通过。
**作者没有验证的部分**：前端没有编译过（R1 出现类型错误属于预期）；Flink 航班作业、ClickHouse 迁移、网关容器没有真实跑过。

---

## R0 准备
1. 确认 W1 已打 tag：`git tag | grep w1`。没有就先 `git tag w1`。
2. 新建分支：`git checkout -b w2`。
3. 把 W2 增量包解压到仓库根目录，**覆盖同名文件**。增量包不包含 README（保留你 R8 写的版本）。
4. `git status` 应只出现增量包清单里的文件（见包内 `W2-FILES.txt`）。提交：`chore: import W2 skeleton`。
5. **人工操作（Agent 不得代做）**：
   - 注册 https://opensky-network.org ，在账号页面创建 API Client，得到 client_id / client_secret。
   - 在 `.env` 里加上（参照新版 `.env.example`）：
     ```
     COLLECTORS=usgs,wiki,opensky
     OPENSKY_CLIENT_ID=...
     OPENSKY_CLIENT_SECRET=...
     OPENSKY_POLL_SECONDS=
     FLIGHT_WINDOW_S=1200
     ```
   - 暂时不想注册：两项留空走匿名，轮询间隔会自动变成 900 秒，`FLIGHT_WINDOW_S` 改成 `2400`。

**验收**：`git status` 里没有 `.env`；`.env` 里 `COLLECTORS` 包含 opensky。

---

## R1 静态检查（Python + 前端编译）
```bash
make dev-setup          # 会给 collectors 和 gateway 各建一个 .venv
make check
cd web && npm install   # 生成 package-lock.json，必须提交
npm run typecheck
npm test
npm run build
cd ..
```
**验收**：`make check` 全绿；`typecheck` 0 错误；vitest 全部通过（3 个文件）；`web/dist/index.html` 存在；
`web/public/textures/earth-night.jpg` 已下载（下载失败只是警告，地球会是纯色，不阻塞）。
提交：`build(web): lockfile and type fixes`。

| 现象 | 处理 |
|---|---|
| `npm install` 很慢或超时 | 国内网络可执行 `npm config set registry https://registry.npmmirror.com` 后重试，不要改 package.json 版本 |
| `globe.gl` 相关类型错误（参数类型不匹配、返回值类型不对） | 允许：按 `node_modules/globe.gl/dist/*.d.ts` 补 `as` 断言或类型标注，**不改调用逻辑**。只限 `web/src/globe/engine.ts` |
| 类型声明里**没有**某个方法（如 `getCoords`、`globeMaterial`、`scene`） | 停下来报告，附上 `.d.ts` 里相关的接口定义 |
| `new Globe(el, {...})` 报「不是构造函数」或参数个数不对 | 停下来报告，附上 globe.gl 版本（`npm ls globe.gl`）和 README 里的初始化写法 |
| three 的类型错误（`setUsage`、`BufferAttribute` 等） | 只允许补类型；`npm ls three` 如显示多个版本，停下来报告 |
| `noUnusedLocals` 报未使用变量 | 删除该未使用的 import / 变量即可 |
| vitest 某个断言失败 | 视为真实 bug：分析原因并报告，**不得改测试** |
| 贴图三个镜像都下载失败 | 不阻塞。可手动把 `earth-night.jpg` 放到 `web/public/textures/` |

---

## R2 ClickHouse 迁移 + Topic 保留时间
```bash
make ch-migrate
make topics-w2
```
**验收**：
- `docker compose exec -T clickhouse clickhouse-client --user du --password du_dev -q "SELECT engine_full FROM system.tables WHERE database='du' AND name='events'" | grep opensky` 有输出
- 再执行一次 `make ch-migrate` 仍然成功（幂等）
- `docker compose exec -T redpanda rpk topic describe evt.unified -c | grep retention.ms` 显示 `21600000`

| 现象 | 处理 |
|---|---|
| `MODIFY TTL` 语法错误 | 原样报告 ClickHouse 版本（`SELECT version()`）和报错，不要删 WHERE 条件 |
| `alter-config` 报 topic 不存在 | 先跑 `docker compose up -d redpanda-init`，确认 6 个 topic 都在 |

---

## R3 采集器加入 OpenSky
```bash
docker compose up -d --build collectors
# 注册账号：等 3 分钟；匿名：首次轮询在启动时立即执行，等 1 分钟即可
docker compose logs --tail=80 collectors | grep -E "opensky|config error"
docker compose exec -T redpanda rpk topic consume raw.opensky -n 2
```
**验收**：
- 日志有 `opensky mode=oauth`（或 `anonymous`）和 `opensky poll ok: emitted=<几千>`
- 消费到的消息字段与 contracts.md 的 raw.opensky 完全一致，经纬度在合理范围
- wiki、usgs 的指标日志仍然正常（W1 不受影响）

| 现象 | 处理 |
|---|---|
| `[config error] OPENSKY_...` | 按报错提示让人修 .env，不要改 config.py 里的最小间隔 |
| `401` / `token rejected` 反复出现 | client_id / secret 错误或已失效，报告人工处理 |
| `rate limited, retry after N s` | 额度用完，正常现象，等待即可；**不要调小轮询间隔** |
| `ConnectTimeout` 到 opensky-network.org / auth.opensky-network.org | 网络问题，报告人工处理（可能需要代理） |
| `emitted=0 filtered=<全部>` | 检查宿主机/容器时钟（位置时间早于响应 60 秒会被过滤），报告 `date -u` 输出 |

---

## R4 提交 Flink 航班作业
```bash
make flink-submit-opensky
make flink-submit-opensky      # 第二次应提示「已在运行，跳过提交」
docker compose exec -T jobmanager ./bin/flink list -r
```
等 3 分钟后：
```bash
docker compose exec -T clickhouse clickhouse-client --user du --password du_dev --database du -q "
SELECT source, count(), max(_inserted_at) FROM events WHERE _inserted_at > now64(3) - INTERVAL 10 MINUTE GROUP BY source"
```
**验收**：`data-universe-w1` 与 `data-universe-w2-opensky` 各有 1 个 RUNNING；ClickHouse 里三个 source 都有数据；Checkpoints 页两个作业都在持续 COMPLETED。

| 现象 | 处理 |
|---|---|
| `Cannot determine simple type name "org"` | 同 W1：确认 Flink 镜像是带完整 planner 的版本（W1 已修） |
| opensky 的 `attrs` 在 ClickHouse 里是空字符串 | 原样报告一条 `evt.unified` 中的 opensky 消息，不要改 JSON_OBJECT |
| W1 作业受到影响（重启 / 失败） | 立即停下报告。W2 不允许改动 W1 作业 |

---

## R5 启动网关
```bash
docker compose up -d --build gateway
curl -s localhost:8090/healthz
curl -s localhost:8090/api/metrics | head -c 600
```
**验收**：`healthz` 中 `kafka_ok: true`；`/api/metrics` 中 `eps.wiki > 1`、`flights_tracked > 500`、`clickhouse_ok: true`；
`docker compose ps gateway` 为 healthy。

| 现象 | 处理 |
|---|---|
| `kafka_ok: false` 且日志反复 `kafka error` | 确认网关容器里用的是 `redpanda:9092`（不是 19092） |
| `clickhouse_ok: false` | `docker compose logs gateway` 里找 `clickhouse ... failed` 的完整报错并报告 |
| `flights_tracked` 为 0 但 ClickHouse 有 opensky 数据 | 网关只统计启动后收到的 + 快照；检查 FLIGHT_WINDOW_S 是否小于轮询间隔 |
| GET / 返回 503「前端未构建」 | 先做 R6 的 `make web-build` |

---

## R6 前端联调
```bash
make web-build      # 构建并自动重启 gateway
```
浏览器打开 http://localhost:8090 ，逐项检查（**截图存 `docs/assets/w2-*.png`**）：

| # | 检查项 | 期望 |
|---|---|---|
| 1 | 首屏 | 3 秒内出现地球；夜景贴图（或纯色降级）；星空背景；地球缓慢自转 |
| 2 | 维基图层 | 青色点不断闪现后变暗，分布在各语言主要国家附近（散开，不是叠成一个点） |
| 3 | 地震图层 | 红色涟漪，位置在板块边缘（环太平洋、阿拉斯加、加州等） |
| 4 | 航班图层 | 黄/橙色小点，欧美航线密集，**缓慢移动**（盯 10 秒能看出位移），不跳点 |
| 5 | 图层开关 | 左上角三个开关能隐藏 / 显示对应图层 |
| 6 | 指标面板 | 四个卡片有数值；趋势图有曲线；数据源三个绿点；热点地区有列表 |
| 7 | 地震列表 | 点击任一条，地球旋转飞到该位置，15 秒后恢复自转 |
| 8 | 底部 HUD | FPS ≥ 55；显示连接状态「已连接」；没有 ⚠ 警告 |
| 9 | 点位正确性 | 加州附近的地震确实落在美国西海岸（验证坐标换算没错） |
| 10 | 背面遮挡 | 转到背面的点被地球挡住，不会透出来 |

开发模式（改样式时用）：`make web-dev` → http://localhost:5173（自动代理到网关）。

| 现象 | 处理 |
|---|---|
| HUD 出现「坐标换算自检失败」 | 停下来报告，附浏览器控制台里 `[DU] 坐标换算` 那条日志的完整内容。**不要改 coords.ts** |
| 地球出现但没有任何点，HUD 显示已连接 | 浏览器控制台、Network → WS 里看消息，报告前 5 条消息内容 |
| 点全部叠在几个位置 | 检查 `REGION_JITTER_DEG` 是否生效；报告截图 |
| 背面的点透出来 | 报告截图（深度测试问题），不要改成关闭深度 |
| 航班点不动 | 控制台执行 `__DU_STATS__` 确认帧率正常后报告；检查 OpenSky 返回的 velocity / heading 是否为空 |
| 点太大 / 太暗 / 颜色不好看 | 只允许改 `web/src/globe/style.ts` |
| HUD 提示时钟相差 N 秒 | WSL2 / Docker Desktop 休眠后时钟漂移：`wsl --shutdown` 或重启 Docker Desktop |

---

## R7 端到端验收
网关至少运行 5 分钟后：
```bash
make verify          # W1 回归，必须仍然全绿
make verify-w2
```
**验收**：两个脚本都全部 PASS。

| 现象 | 处理 |
|---|---|
| 「可对比的完整分钟只有 N 个」 | 网关刚重启，再等 3 分钟重跑；这不是失败原因，不要改脚本 |
| 首屏耗时 > 1s | 报告 `/api/metrics` 中 `clickhouse_ok` 和 ClickHouse 慢查询（`system.query_log` 最近 10 条耗时） |
| 合包节拍偏离 tick 整数倍 p95 > 30ms，或最小间隔 < tick−30ms | 报告网关 CPU（`docker stats --no-stream`）和 `docker compose logs gateway` 最后 50 行 |
| 采集 -> 客户端 p95 > 2000ms | 先排除时钟漂移（上一节），再报告 `/api/metrics` 中的 `lag_ms` |
| 网关/ClickHouse 对数比例超出 0.95~1.05 | 报告 `/api/debug/minute_counts?source=wiki` 的完整输出 |

---

## R8 FPS 压测
```bash
cd web && npx playwright install chromium && cd ..
make bench
```
会弹出一个浏览器窗口跑约 40 秒，**期间不要操作电脑、不要最小化窗口**。
也可以手动打开 http://localhost:8090/?bench=1 看结果面板。

**验收**：输出 `PASS`；结果文件写入 `benchmarks/results/fps-*.json`（提交）；GPU 字段不是 SwiftShader / llvmpipe。

| 现象 | 处理 |
|---|---|
| GPU 显示 SwiftShader / Software | 浏览器没用上显卡：确认不是远程桌面；笔记本接上电源并设为高性能模式后重跑 |
| 平均帧率 ≈ 30 / 显示器刷新率很低 | 记录显示器刷新率后报告；**不允许降低阈值** |
| FAIL 且确为硬件 GPU | 报告结果 JSON 和 Chrome 的 Performance 面板截图（录 5 秒），不要自行改渲染代码 |

---

## R9 健壮性
```bash
# 9.1 网关重启：浏览器 30 秒内自动重连，快照重新铺满地球
docker compose restart gateway        # 同时盯着浏览器 HUD
# 9.2 航班作业 savepoint 停止 / 恢复
make flink-stop-opensky               # 记下 savepoint 路径
make flink-resume-opensky SAVEPOINT=<路径>
# 9.3 回归
sleep 300 && make verify && make verify-w2
```
**验收**：9.1 HUD 先显示「已断开，N 秒后重连」再回到「已连接」，地球上的点重新出现；9.3 两个脚本全绿。

---

## R10 收尾
- 录 15～30 秒 GIF（Windows 可用 ScreenToGif）：自转 → 打开 / 关闭航班图层 → 点击一条地震飞过去。存 `docs/assets/demo.gif`，控制在 10MB 以内
- README：首屏放 GIF；补充 `make web-build`、8090 端口、`make bench` 结果
- 提交 `docs: W2 visualization verified`，合并回主分支，`git tag w2`

## 完成定义（DoD）
- [ ] `make check`、`npm run typecheck`、`npm test`、`npm run build` 全绿
- [ ] `make verify`、`make verify-w2` 全绿（R7、R9 各一轮）
- [ ] `make bench` PASS，结果 JSON 已提交
- [ ] R6 十项检查全部符合，截图已提交
- [ ] `git diff w1 --stat` 自查：没有改动 `00_ddl.sql`、`10_pipeline.sql`、`tests/` 和 fixtures 里的旧文件、验收阈值
