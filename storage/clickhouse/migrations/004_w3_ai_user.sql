-- W3：AI 提问专用只读账号（SQL 守卫之外的第二道防线）。幂等。由 make ch-migrate 执行。
-- readonly = 2：只能读，但允许在查询里调小 max_execution_time 等设置；不授予 CREATE TEMPORARY TABLE，表函数（url/file/remote）也无法使用。
-- 密码仅用于本地开发；公开部署时 ClickHouse 不对外暴露端口，如需修改：ALTER USER du_ai IDENTIFIED BY '<新密码>' 并同步 .env 的 AI_CH_PASSWORD。
CREATE USER IF NOT EXISTS du_ai IDENTIFIED WITH sha256_password BY 'du_ai_dev'
    DEFAULT DATABASE du
    SETTINGS readonly = 2,
             max_execution_time = 10 MAX 15,
             max_memory_usage = 1000000000 MAX 2000000000,
             max_result_rows = 1000 MAX 1000;

GRANT SELECT ON du.events TO du_ai;
GRANT SELECT ON du.agg_minute TO du_ai;
GRANT SELECT ON du.alerts TO du_ai;
