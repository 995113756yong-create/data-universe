import asyncio

import orjson
from conftest import FakeWS, flight_evt, wiki_evt

from gateway.protocol import encode
from gateway.session import ClientSession


def _offer(s, evt):
    layer, key, row = encode(evt)
    s.offer(layer, key, row)


def test_build_batch_groups_by_layer(settings):
    s = ClientSession(FakeWS(), settings)
    assert s.build_batch() is None
    for i in range(80):
        _offer(s, wiki_evt(i))
    _offer(s, flight_evt("a", 1000))
    _offer(s, flight_evt("a", 2000))
    b = s.build_batch()
    assert len(b["rows"]["wiki"]) == 50 and b["dropped"]["wiki"] == 30
    assert len(b["rows"]["opensky"]) == 1 and b["rows"]["opensky"][0][6] == 2000


def test_subscribe_filters_layers(settings):
    s = ClientSession(FakeWS(), settings)
    _offer(s, wiki_evt(1))
    s.handle_client_message(orjson.dumps({"t": "subscribe", "layers": ["opensky", "bad"]}).decode())
    assert s.layers == {"opensky"}
    _offer(s, wiki_evt(2))
    assert s.build_batch() is None  # 已缓冲的 wiki 也被清掉


def test_load_feedback_lowers_cap(settings):
    s = ClientSession(FakeWS(), settings)
    s.handle_client_message('{"t":"load","fps":30}')
    assert s.cap.value == 25 and s.buffers["wiki"].cap == 25
    s.handle_client_message("not json")
    s.handle_client_message('{"t":"load","fps":"x"}')
    assert s.cap.value == 25


def test_send_loop_ticks(settings):
    ws = FakeWS()
    s = ClientSession(ws, settings)

    async def go():
        task = asyncio.create_task(s.send_loop())
        for i in range(10):
            _offer(s, wiki_evt(i))
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.06)
        task.cancel()

    asyncio.run(go())
    batches = [orjson.loads(x) for x in ws.sent]
    assert sum(len(b["rows"].get("wiki", [])) for b in batches) == 10
    assert 5 <= len(batches) <= 11  # 50ms tick 下约每个 tick 一包


def test_slow_client_degrades(settings):
    ws = FakeWS(send_delay=0.12)  # 每次发送耗时超过 tick（50ms）
    s = ClientSession(ws, settings)

    async def go():
        task = asyncio.create_task(s.send_loop())
        for i in range(30):
            for j in range(20):
                _offer(s, wiki_evt(i * 100 + j))
            await asyncio.sleep(0.02)
        task.cancel()

    asyncio.run(go())
    assert s.cap.value == settings.wiki_cap_min
    assert s.skipped_ticks > 0
    # 内存有上限：wiki 缓冲区不会超过 cap
    assert len(s.buffers["wiki"]) <= settings.wiki_cap


def test_control_queue_keeps_latest(settings):
    s = ClientSession(FakeWS(), settings)
    for i in range(50):
        s.push_control({"t": "metrics", "i": i})
    assert s._control.qsize() == 20
