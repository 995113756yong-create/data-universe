-- W2 迁移：航班数据量大（全球约 1 万架 / 轮询），明细只保留 1 天；其余数据源仍保留 7 天。
-- 幂等：MODIFY TTL 重复执行结果相同。由 make ch-migrate 执行（新装和已有环境都要执行）。
ALTER TABLE du.events
    MODIFY TTL
        toDateTime(event_time) + INTERVAL 1 DAY DELETE WHERE source = 'opensky',
        toDateTime(event_time) + INTERVAL 7 DAY;
