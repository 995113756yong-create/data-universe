SHELL := /bin/bash
COMPOSE := docker compose
JOB_NAME := data-universe-w1
OS_JOB_NAME := data-universe-w2-opensky
AL_JOB_NAME := data-universe-w3-alerts
PY := gateway/.venv/bin/python
REPLAY_ARGS ?= --minutes 60
SQL_DIR := /opt/flink/sql

.PHONY: help env up down clean ps logs flink-wait flink-status flink-submit flink-stop flink-resume \
        ch topics verify dev-setup test lint fmt check \
        ch-migrate topics-w2 flink-submit-opensky flink-stop-opensky flink-resume-opensky \
        web-install web-dev web-build web-test bench verify-w2 \
        flink-submit-alerts flink-stop-alerts flink-resume-alerts replay-export web-build-static verify-w3

help:
	@echo "make up            一键启动全链路并提交 Flink 作业"
	@echo "make verify        端到端验收（启动后至少等 3 分钟再跑）"
	@echo "make flink-stop    带 savepoint 停止作业，输出 savepoint 路径"
	@echo "make flink-resume SAVEPOINT=<路径>   从 savepoint 恢复作业"
	@echo "make down / clean  停止 / 停止并删除所有数据卷"
	@echo "make dev-setup && make check    本地单测与 lint"
	@echo "---- W2 ----"
	@echo "make web-install / web-build / web-test   前端依赖、构建（构建后自动重启 gateway）、测试"
	@echo "make verify-w2     W2 端到端验收"
	@echo "make bench         FPS 压测（需要有界面的浏览器）"
	@echo "make flink-stop-opensky / flink-resume-opensky SAVEPOINT=<路径>"
	@echo "---- W3 ----"
	@echo "make verify-w3     W3 端到端验收（告警对账、AI 提问、回放包）"
	@echo "make replay-export [REPLAY_ARGS='--minutes 60']   导出回放包到 web/public/replay"
	@echo "make web-build-static   构建纯静态回放站点到 web/dist-static（GitHub Pages）"
	@echo "make flink-stop-alerts / flink-resume-alerts SAVEPOINT=<路径>"

env:
	@if [ ! -f .env ]; then cp .env.example .env; \
	  echo "已生成 .env，请先把 HTTP_USER_AGENT 改成你自己的 GitHub 地址和邮箱，再重新执行"; exit 1; fi
	@if grep -q '<' .env; then echo ".env 里仍有 <占位符>，请先修改"; exit 1; fi

up: env
	$(COMPOSE) up -d --build
	$(MAKE) flink-wait
	$(MAKE) ch-migrate
	$(MAKE) topics-w2
	$(MAKE) flink-submit
	$(MAKE) flink-submit-opensky
	$(MAKE) flink-submit-alerts

down:
	$(COMPOSE) down

clean:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100 collectors

topics:
	$(COMPOSE) exec -T redpanda rpk topic list

ch:
	$(COMPOSE) exec clickhouse clickhouse-client --user du --password du_dev --database du

flink-wait:
	@for i in $$(seq 1 60); do \
	  if curl -sf localhost:8081/overview | grep -q '"taskmanagers":[1-9]'; then echo "Flink ready"; exit 0; fi; \
	  sleep 2; done; echo "Flink 120s 内未就绪"; exit 1

flink-status:
	@$(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | grep ': $(JOB_NAME) (' || echo "no running job named $(JOB_NAME)"

# 幂等：已有同名作业在运行就跳过，防止重复提交导致数据翻倍
flink-submit:
	@n=$$($(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | grep -c ': $(JOB_NAME) (RUNNING)' || true); \
	if [ "$$n" != "0" ]; then echo "作业 $(JOB_NAME) 已在运行（$$n 个），跳过提交"; exit 0; fi; \
	$(COMPOSE) exec -T jobmanager ./bin/sql-client.sh -i $(SQL_DIR)/00_ddl.sql -f $(SQL_DIR)/10_pipeline.sql

flink-stop:
	@id=$$($(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | awk -F' : ' '/: $(JOB_NAME) \(RUNNING\)/ {print $$2}' | head -1); \
	if [ -z "$$id" ]; then echo "没有运行中的 $(JOB_NAME)"; exit 1; fi; \
	$(COMPOSE) exec -T jobmanager ./bin/flink stop --savepointPath /opt/flink/savepoints $$id

flink-resume:
	@if [ -z "$(SAVEPOINT)" ]; then echo "用法: make flink-resume SAVEPOINT=/opt/flink/savepoints/savepoint-xxxx"; exit 1; fi
	$(COMPOSE) exec -T jobmanager bash -c "{ echo \"SET 'execution.savepoint.path' = '$(SAVEPOINT)';\"; cat $(SQL_DIR)/10_pipeline.sql; } > /tmp/resume.sql && ./bin/sql-client.sh -i $(SQL_DIR)/00_ddl.sql -f /tmp/resume.sql"

verify:
	bash scripts/verify.sh

# ---------------- W2 ----------------
ch-migrate:
	bash scripts/ch_migrate.sh

topics-w2:
	bash scripts/w2_topics.sh

flink-submit-opensky:
	@n=$$($(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | grep -c ': $(OS_JOB_NAME) (RUNNING)' || true); \
	if [ "$$n" != "0" ]; then echo "作业 $(OS_JOB_NAME) 已在运行（$$n 个），跳过提交"; exit 0; fi; \
	$(COMPOSE) exec -T jobmanager ./bin/sql-client.sh -i $(SQL_DIR)/20_opensky_ddl.sql -f $(SQL_DIR)/21_opensky_pipeline.sql

flink-stop-opensky:
	@id=$$($(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | awk -F' : ' '/: $(OS_JOB_NAME) \(RUNNING\)/ {print $$2}' | head -1); \
	if [ -z "$$id" ]; then echo "没有运行中的 $(OS_JOB_NAME)"; exit 1; fi; \
	$(COMPOSE) exec -T jobmanager ./bin/flink stop --savepointPath /opt/flink/savepoints $$id

flink-resume-opensky:
	@if [ -z "$(SAVEPOINT)" ]; then echo "用法: make flink-resume-opensky SAVEPOINT=/opt/flink/savepoints/savepoint-xxxx"; exit 1; fi
	$(COMPOSE) exec -T jobmanager bash -c "{ echo \"SET 'execution.savepoint.path' = '$(SAVEPOINT)';\"; cat $(SQL_DIR)/21_opensky_pipeline.sql; } > /tmp/resume_os.sql && ./bin/sql-client.sh -i $(SQL_DIR)/20_opensky_ddl.sql -f /tmp/resume_os.sql"

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build
	@if $(COMPOSE) ps --services --status running 2>/dev/null | grep -qx gateway; then $(COMPOSE) restart gateway; fi

web-test:
	cd web && npm run typecheck && npm test

bench:
	cd web && npm run bench

verify-w2:
	$(PY) scripts/verify_w2.py

# ---------------- W3 ----------------
flink-submit-alerts:
	@n=$$($(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | grep -c ': $(AL_JOB_NAME) (RUNNING)' || true); \
	if [ "$$n" != "0" ]; then echo "作业 $(AL_JOB_NAME) 已在运行（$$n 个），跳过提交"; exit 0; fi; \
	$(COMPOSE) exec -T jobmanager ./bin/sql-client.sh -i $(SQL_DIR)/30_alerts_ddl.sql -f $(SQL_DIR)/31_alerts_pipeline.sql

flink-stop-alerts:
	@id=$$($(COMPOSE) exec -T jobmanager ./bin/flink list -r 2>/dev/null | awk -F' : ' '/: $(AL_JOB_NAME) \(RUNNING\)/ {print $$2}' | head -1); \
	if [ -z "$$id" ]; then echo "没有运行中的 $(AL_JOB_NAME)"; exit 1; fi; \
	$(COMPOSE) exec -T jobmanager ./bin/flink stop --savepointPath /opt/flink/savepoints $$id

flink-resume-alerts:
	@if [ -z "$(SAVEPOINT)" ]; then echo "用法: make flink-resume-alerts SAVEPOINT=/opt/flink/savepoints/savepoint-xxxx"; exit 1; fi
	$(COMPOSE) exec -T jobmanager bash -c "{ echo \"SET 'execution.savepoint.path' = '$(SAVEPOINT)';\"; cat $(SQL_DIR)/31_alerts_pipeline.sql; } > /tmp/resume_al.sql && ./bin/sql-client.sh -i $(SQL_DIR)/30_alerts_ddl.sql -f /tmp/resume_al.sql"

replay-export:
	$(PY) -m gateway.replay_export --out web/public/replay $(REPLAY_ARGS)

web-build-static:
	cd web && npm run build:static

verify-w3:
	$(PY) scripts/verify_w3.py

dev-setup:
	cd collectors && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e '.[dev]'
	cd gateway && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e '.[dev]'

test:
	cd collectors && .venv/bin/pytest -q
	cd gateway && .venv/bin/pytest -q
	collectors/.venv/bin/pytest -q tests

lint:
	cd collectors && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd gateway && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd collectors && .venv/bin/ruff format . && .venv/bin/ruff check --fix .
	cd gateway && .venv/bin/ruff format . && .venv/bin/ruff check --fix .

check: lint test
	$(COMPOSE) config -q && echo "compose config ok"
	@for f in scripts/*.sh infra/redpanda/create_topics.sh; do bash -n $$f || exit 1; done; echo "shell syntax ok"
