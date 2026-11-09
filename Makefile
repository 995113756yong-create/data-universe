SHELL := /bin/bash
COMPOSE := docker compose
JOB_NAME := data-universe-w1
SQL_DIR := /opt/flink/sql

.PHONY: help env up down clean ps logs flink-wait flink-status flink-submit flink-stop flink-resume \
        ch topics verify dev-setup test lint fmt check

help:
	@echo "make up            一键启动全链路并提交 Flink 作业"
	@echo "make verify        端到端验收（启动后至少等 3 分钟再跑）"
	@echo "make flink-stop    带 savepoint 停止作业，输出 savepoint 路径"
	@echo "make flink-resume SAVEPOINT=<路径>   从 savepoint 恢复作业"
	@echo "make down / clean  停止 / 停止并删除所有数据卷"
	@echo "make dev-setup && make check    本地单测与 lint"

env:
	@if [ ! -f .env ]; then cp .env.example .env; \
	  echo "已生成 .env，请先把 HTTP_USER_AGENT 改成你自己的 GitHub 地址和邮箱，再重新执行"; exit 1; fi
	@if grep -q '<' .env; then echo ".env 里仍有 <占位符>，请先修改"; exit 1; fi

up: env
	$(COMPOSE) up -d --build
	$(MAKE) flink-wait
	$(MAKE) flink-submit

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

dev-setup:
	cd collectors && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -e '.[dev]'

test:
	cd collectors && .venv/bin/pytest -q

lint:
	cd collectors && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd collectors && .venv/bin/ruff format . && .venv/bin/ruff check --fix .

check: lint test
	$(COMPOSE) config -q && echo "compose config ok"
	@for f in scripts/verify.sh infra/redpanda/create_topics.sh; do bash -n $$f || exit 1; done; echo "shell syntax ok"
