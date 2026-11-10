import asyncio

import orjson
from conftest import FakeCH, FakeWS, alert_raw

from gateway.alerts import AlertStore, load_centroids, normalize
from gateway.hub import Hub
from gateway.session import ClientSession

CENT = load_centroids()


def test_wiki_alert_gets_region_centroid():
    a = normalize(alert_raw(), CENT)
    assert a["geo_precision"] == "approx"
    assert (a["lat"], a["lng"]) == CENT["Germany"]
    assert a["baseline_std"] == 6.12  # 保留两位小数


def test_quake_alert_keeps_exact_coords():
    a = normalize(
        alert_raw("quake-x", "quake_significant", region="Japan", lat=36.12346, lng=140.5), CENT
    )
    assert a["geo_precision"] == "exact" and a["lat"] == 36.1235


def test_unknown_region_without_coords():
    a = normalize(alert_raw(region="Atlantis"), CENT)
    assert a["lat"] is None and a["geo_precision"] == "none"


def test_reject_invalid():
    assert normalize(None, CENT) is None
    assert normalize({"alert_id": "x", "alert_type": "nope"}, CENT) is None
    bad = alert_raw()
    bad["event_time_ms"] = "abc"
    assert normalize(bad, CENT) is None


def test_store_dedup_and_order():
    st = AlertStore(max_items=3)
    assert st.upsert(normalize(alert_raw("a", t=1000), CENT)) is True
    assert st.upsert(normalize(alert_raw("a", t=1000, value=99), CENT)) is False  # 修订
    st.upsert(normalize(alert_raw("b", t=3000), CENT))
    st.upsert(normalize(alert_raw("c", t=2000), CENT))
    st.upsert(normalize(alert_raw("d", t=4000), CENT))
    assert len(st) == 3
    assert [a["alert_id"] for a in st.recent()] == ["d", "b", "c"]  # a 被淘汰
    assert st.count_since(2500) == 2


def test_hub_broadcasts_alert(settings):
    hub = Hub(settings, FakeCH())
    s = ClientSession(FakeWS(), settings)
    hub.clients.add(s)
    hub.ingest_alert(alert_raw())
    hub.ingest_alert(alert_raw())  # 重复
    msgs = [orjson.loads(s._control.get_nowait()) for _ in range(s._control.qsize())]
    assert [m["new"] for m in msgs] == [True, False]
    assert msgs[0]["alert"]["region"] == "Germany"
    assert hub.alerts_received == 2


def test_hub_consume_routes_by_topic(settings):
    from conftest import wiki_evt

    hub = Hub(settings, FakeCH())

    async def source():
        yield ("evt.unified", wiki_evt(1))
        yield ("alert.anomaly", alert_raw())
        yield wiki_evt(2)  # 兼容直接产出 dict

    asyncio.run(hub.consume(source))
    assert hub.consumed == 2 and len(hub.alerts) == 1


def test_alert_snapshot_merges_memory(settings):
    hub = Hub(settings, FakeCH())
    hub.ingest_alert(alert_raw())
    rows = asyncio.run(hub._alert_snapshot())
    assert {r["alert_id"] for r in rows} == {"quake-us1", "wiki_spike-Germany-2026-11-10 08:00:00"}
