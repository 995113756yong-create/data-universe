import random

from gateway.adaptive import AdaptiveCap
from gateway.buffers import CoalescingBuffer, KeepAllBuffer, ReservoirBuffer
from gateway.rolling import LagStats, MinuteCounter, RollingCounter


def test_reservoir_caps_and_counts_dropped():
    b = ReservoirBuffer(cap=100, rng=random.Random(1))
    for i in range(1000):
        b.offer(str(i), [i])
    items, dropped = b.drain()
    assert len(items) == 100 and dropped == 900
    assert b.drain() == ([], 0)
    assert b.dropped_total == 900


def test_reservoir_sample_is_uniform_over_time():
    # 不是只保留最前或最后 100 条：样本应覆盖整个区间
    b = ReservoirBuffer(cap=100, rng=random.Random(7))
    for i in range(10_000):
        b.offer(str(i), [i])
    vals = sorted(r[0] for r in b.drain()[0])
    assert vals[0] < 1000 and vals[-1] > 9000
    assert 3500 < sum(vals) / len(vals) < 6500


def test_reservoir_under_cap_keeps_all():
    b = ReservoirBuffer(cap=10)
    for i in range(5):
        b.offer(str(i), [i])
    assert b.drain() == ([[0], [1], [2], [3], [4]], 0)


def test_keep_all_with_safety_limit():
    b = KeepAllBuffer(max_items=3)
    for i in range(5):
        b.offer(str(i), [i])
    assert b.drain() == ([[2], [3], [4]], 0)
    assert b.dropped_total == 2


def test_coalescing_keeps_latest_and_carries_over():
    b = CoalescingBuffer(cap=2)
    b.offer("a", ["a", 1])
    b.offer("b", ["b", 1])
    b.offer("c", ["c", 1])
    b.offer("a", ["a", 2])  # 合并：a 只保留最新，并排到队尾
    items, _ = b.drain()
    assert items == [["b", 1], ["c", 1]]
    assert len(b) == 1
    assert b.drain()[0] == [["a", 2]]
    assert b.coalesced_total == 1


def test_adaptive_cap_aimd():
    c = AdaptiveCap(initial=200, minimum=20)
    assert c.on_fps(30) == 100
    assert c.on_fps(30) == 50
    assert c.on_fps(30) == 25
    assert c.on_fps(30) == 20  # 不低于下限
    assert c.on_fps(50) == 20  # 45~55 之间保持不变
    for _ in range(50):
        c.on_fps(60)
    assert c.value == 200  # 不超过上限
    assert c.on_send(send_ms=190, tick_ms=200) == 100


def test_rolling_counter_rate_excludes_current_second():
    r = RollingCounter()
    for s in range(100, 111):
        r.add("wiki", s, 10)
    assert r.total("wiki", 110, 10) == 100
    assert r.rate("wiki", 110, 10) == 10.0


def test_lag_quantiles():
    lag = LagStats()
    for v in range(1, 101):
        lag.add("wiki", v)
    lag.add("wiki", -5)  # 时钟回拨的负值忽略
    q = lag.quantiles("wiki")
    assert q["n"] == 100 and q["p50"] == 51 and q["p95"] == 96
    assert lag.quantiles("usgs") is None


def test_minute_counter_dedup_and_retention():
    m = MinuteCounter(keep_minutes=2)
    m.add("wiki", "a", 60_000)
    m.add("wiki", "a", 61_000)  # 重复投递不重复计数
    m.add("wiki", "b", 119_999)
    m.add("wiki", "c", 120_000)
    m.add("wiki", "d", 180_000)
    assert m.snapshot("wiki") == {120_000: 1, 180_000: 1}
