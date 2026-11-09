# AGENTS.md — 给 AI 编码 Agent 的强制规则

> 本文件优先级最高。和其他文档冲突时以本文件为准。Claude Code 用户可执行 `cp AGENTS.md CLAUDE.md`。

## 项目是什么
Data Universe：把公开实时数据流（USGS 地震、Wikipedia 编辑）经 Redpanda → Flink SQL → ClickHouse 处理入库，后续做 3D 地球可视化。
当前阶段：**W1 数据链路**。代码已经全部写好，**你的任务是按 `docs/tasks/W1-runbook.md` 运行、验收、修复**，不是重写。

## 你的工作方式
1. 一次只做 runbook 里的一个步骤（R0、R1……），做完跑该步骤的「验收」命令。
2. 验收通过 → `git add` 相关文件 → `git commit`（Conventional Commits，例如 `fix(flink): ...`）→ 进入下一步。
3. 验收失败 → 按 runbook 的「排错表」处理；排错表没覆盖的，**停下来报告**（格式见文末），不要自己发挥。
4. 每次修改前先说明：要改哪个文件、为什么、预期效果。

## 绝对禁止（违反任何一条即视为任务失败）
- ❌ 修改数据契约：`docs/contracts.md` 中的 topic 名、字段名、字段类型、字段顺序。
- ❌ 删除、跳过（skip/xfail）或改弱任何测试断言；删除或修改 `collectors/tests/fixtures/` 里已有的样本。
- ❌ 调低 `scripts/verify.sh` 里的阈值，或者删检查项，或者把 `fail` 改成 `pass`。
- ❌ 新增或替换技术组件（例如把 Redpanda 换成 Kafka，Flink 换成 Spark，ClickHouse 换成别的库，加 Redis、加 Python 流处理来绕开 Flink）。
- ❌ 修改端口、服务名、topic 分区数。
- ❌ 使用 `latest` 镜像 tag；引入 `pyproject.toml` 以外的新 Python 依赖。
- ❌ 提交 `.env` 或任何密钥；在代码里写死 User-Agent 联系方式。
- ❌ 为了让作业跑起来而去掉 watermark、去掉 `WHERE event_id IS NOT NULL` 之类的防御逻辑。
- ❌ 一次性大范围重构或改格式（只改与当前问题直接相关的行）。
- ❌ 开发 W1 范围以外的功能（前端、网关、AI、告警、OpenSky）。

## 允许的修改（白名单）
- ✅ 镜像 tag 拉不到时，换成**同一大版本**里存在的 tag（例如 `v24.2.7` → `v24.2.x`），并在 commit message 里写明原因。
- ✅ Flink Kafka connector jar 下载失败时，换成 Maven Central 上与 **Flink 1.18** 匹配的版本。
- ✅ 修复真实 bug：必须**先补一个能复现该 bug 的测试**（测试先失败），再改代码让它通过。
- ✅ 外部 API 字段确实变了：停下来报告，附上真实返回样本，等人确认后再改。
- ✅ 更新 README 的运行说明。

## 必须遵守的工程约定
- Python 3.11；`make check` 全绿（ruff + pytest + compose config + shell 语法）。
- 时间统一用 UTC epoch 毫秒传输，只在 ClickHouse 落表时转 DateTime64。
- 解析逻辑保持纯函数（`*/parser.py`），IO 只在 `poller.py` / `sse_client.py`。
- ClickHouse 的 schema 只在 `storage/clickhouse/init/001_schema.sql` 里改，改完需要 `make clean && make up` 才生效。

## 停下来报告的格式
```
【卡住的步骤】R?
【执行的命令】...
【完整报错】（原样粘贴，不要概括）
【我的判断】可能原因 1～2 条
【建议方案】A / B，各自要改哪些文件
【等待确认】是
```
