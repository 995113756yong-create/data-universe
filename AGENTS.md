# AGENTS.md — 给 AI 编码 Agent 的强制规则

> 本文件优先级最高。和其他文档冲突时以本文件为准。Claude Code 用户可执行 `cp AGENTS.md CLAUDE.md`。

## 项目是什么
Data Universe：把公开实时数据流（USGS 地震、Wikipedia 编辑、OpenSky 航班）经 Redpanda → Flink SQL → ClickHouse 处理，
再通过 WebSocket 网关推到浏览器里的 3D 地球上。

当前阶段：**W3 智能化**——异常告警、AI 自然语言提问、回放模式（W1、W2 已完成，打了 tag `w1`、`w2`）。
W3 代码已经全部写好，**你的任务是按 `docs/tasks/W3-runbook.md` 运行、验收、修复**，不是重写。

## 你的工作方式
1. 一次只做 runbook 里的一个步骤（R0、R1……），做完跑该步骤的「验收」命令。
2. 验收通过 → `git add` 相关文件 → `git commit`（Conventional Commits，例如 `fix(web): ...`）→ 进入下一步。
3. 验收失败 → 按 runbook 的「排错表」处理；排错表没覆盖的，**停下来报告**（格式见文末），不要自己发挥。
4. 每次修改前先说明：要改哪个文件、为什么、预期效果。

## 绝对禁止（违反任何一条即视为任务失败）
### 通用
- ❌ 修改数据契约：`docs/contracts.md` 中的 topic 名、字段名、字段类型、字段顺序，以及 WebSocket 协议的数组列顺序。
- ❌ 删除、跳过（skip / xfail / `it.skip`）或改弱任何测试断言；删除或修改 `collectors/tests/fixtures/` 里已有的样本。
- ❌ 调低 `scripts/verify.sh`、`scripts/verify_w2.py`、`scripts/verify_w3.py`、`web/src/bench/synthetic.ts`（BENCH 常量）里的阈值，删检查项，或把失败改成通过。
- ❌ 新增或替换技术组件（Redpanda / Flink / ClickHouse / FastAPI / React / globe.gl / three / ECharts 都不能换，不能加 Redis、Nginx 等）。
- ❌ 修改端口、服务名、topic 分区数。
- ❌ 使用 `latest` 镜像 tag；引入 `pyproject.toml` / `package.json` 以外的新依赖（Python 和 npm 都算）。
- ❌ 提交 `.env`、OpenSky 的 client_id / client_secret 或任何密钥；在代码里写死 User-Agent 联系方式。
- ❌ 为了让作业跑起来而去掉 watermark、去掉 `WHERE ... IS NOT NULL` 之类的防御逻辑。
- ❌ 一次性大范围重构或改格式（只改与当前问题直接相关的行）。
- ❌ 开发 W3 范围以外的功能（例如 GitHub 数据源、用户系统、多语言）。

### W2 专项
- ❌ 修改 `streaming/flink-sql/00_ddl.sql`、`10_pipeline.sql`（W1 作业的算子拓扑必须保持不变，否则 W1 的 savepoint 无法恢复）。
- ❌ 让浏览器直接访问 ClickHouse 或 Kafka；前端只能连网关的 `/ws` 和 `/api/*`。
- ❌ 把维基 / 航班图层改成 globe.gl 自带的 `pointsData` / `hexBinPointsData` / `htmlElementsData`（几万个点会掉帧）；高频图层必须保持自定义 `THREE.Points` 实现。
- ❌ 把网关的缓冲策略改成「无上限队列」，或去掉抽样 / 合并 / 背压逻辑。
- ❌ 修改 `web/src/globe/coords.ts` 的换算公式来"凑"位置。坐标自检失败要停下来报告。

### W3 专项
- ❌ 修改 `00_ddl.sql`、`10_pipeline.sql`、`20_opensky_ddl.sql`、`21_opensky_pipeline.sql`（W1/W2 作业拓扑不变）。告警只能在独立作业 `30_alerts_*.sql` 里做。
- ❌ 修改告警阈值（z ≥ 3、多 10 条、基线 10 行、30 分钟窗口、M4.5）。三处（Flink SQL / verify_w3.py / contracts.md）由契约测试锁定。
- ❌ 放宽 `gateway/src/gateway/ai/sqlguard.py` 的白名单 / 黑名单，或让 AI 用 `du` 账号执行 SQL（只能用 `du_ai`）。
- ❌ 给 `du_ai` 增加权限、去掉迁移 004 里的设置上限。
- ❌ 把 LLM API Key 写进代码、前端或提交到 git；让浏览器直接调用模型 API。
- ❌ 去掉 `/api/ask` 的限流、并发上限、问题长度校验。
- ❌ 自行设置 `VERIFY_SKIP_AI=1`（只有仓库所有者本人可以）。
- ✅ 告警标签和 AI 高亮使用 globe.gl 的 `ringsData` / `htmlElementsData`（数量 ≤ 30），不受 W2「高频图层禁止 htmlElementsData」限制。

## 允许的修改（白名单）
- ✅ 镜像 tag 拉不到时，换成**同一大版本**里存在的 tag，并在 commit message 里写明原因。
- ✅ Flink Kafka connector jar 下载失败时，换成 Maven Central 上与 **Flink 1.18** 匹配的版本。
- ✅ 修复真实 bug：必须**先补一个能复现该 bug 的测试**（测试先失败），再改代码让它通过。
- ✅ **TypeScript 类型错误**（R1 预期会出现）：只允许做不改变运行时行为的修改——补类型标注、`as` 断言、`import type`、
  按 `node_modules/globe.gl` 的 `.d.ts` 修正方法名的**类型写法**。如果类型声明显示某个方法**不存在**（不是类型不匹配），停下来报告。
- ✅ 调整 `web/src/globe/style.ts` 里的颜色、尺寸、亮度等视觉常量。
- ✅ 第一次 `npm install` 生成的 `web/package-lock.json` 必须提交。
- ✅ 外部 API 字段确实变了：停下来报告，附上真实返回样本，等人确认后再改。
- ✅ 更新 README 的运行说明和截图。

## 必须遵守的工程约定
- Python 3.11；`make check` 全绿（ruff + pytest：collectors、gateway、tests/ 契约测试 + compose config + shell 语法）。
- 前端：`npm run typecheck`、`npm test`、`npm run build` 全部通过。
- 时间统一用 UTC epoch 毫秒传输，只在 ClickHouse 落表时转 DateTime64。
- 解析逻辑保持纯函数（`*/parser.py`、`web/src/stream/decode.ts`、`web/src/globe/deadReckoning.ts`），IO 只在 poller / sse_client / worker。
- ClickHouse 的 schema 变更一律新增 `storage/clickhouse/migrations/NNN_xxx.sql`（必须幂等），不改 `init/001_schema.sql`。
- Flink 作业停止 / 重启一律走 savepoint（`make flink-stop` / `make flink-stop-opensky` / `make flink-stop-alerts` 和对应的 resume）。
- 回放包体积 ≤ 30MB；`web/public/replay/` 只保留一份演示回放提交到 git（静态站点部署要用）。

## 停下来报告的格式
```
【卡住的步骤】R?
【执行的命令】...
【完整报错】（原样粘贴，不要概括）
【我的判断】可能原因 1～2 条
【建议方案】A / B，各自要改哪些文件
【等待确认】是
```
