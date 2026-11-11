"""alert.anomaly 消息 -> 推给浏览器的告警对象：字段裁剪、坐标补全、去重。"""

from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

ALERT_FIELDS = (
    "alert_id",
    "alert_type",
    "source",
    "region",
    "window_start",
    "event_time_ms",
    "detected_ms",
    "value",
    "baseline_mean",
    "baseline_std",
    "zscore",
    "severity",
    "lat",
    "lng",
    "title",
)
KNOWN_TYPES = frozenset({"wiki_spike", "quake_significant"})


def load_centroids(path: str | Path | None = None) -> dict[str, tuple[float, float]]:
    path = Path(path) if path else Path(__file__).with_name("region_centroids.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: (float(v["lat"]), float(v["lng"])) for k, v in data.items() if not k.startswith("_")}


def _round(v, nd=2):
    return None if v is None else round(float(v), nd)


def normalize(raw: dict, centroids: dict[str, tuple[float, float]]) -> dict | None:
    """非法消息返回 None。没有坐标的告警用地区中心点补全，并标记 geo_precision。"""
    if not isinstance(raw, dict) or not raw.get("alert_id"):
        return None
    if raw.get("alert_type") not in KNOWN_TYPES:
        return None
    try:
        out = {k: raw.get(k) for k in ALERT_FIELDS}
        out["event_time_ms"] = int(out["event_time_ms"] or 0)
        out["detected_ms"] = int(out["detected_ms"] or 0)
        out["value"] = float(out["value"] or 0.0)
    except (TypeError, ValueError):
        return None
    for k in ("baseline_mean", "baseline_std", "zscore"):
        out[k] = _round(out[k])
    out["geo_precision"] = "exact"
    if out["lat"] is None or out["lng"] is None:
        c = centroids.get(out.get("region") or "")
        if c is None:
            out["lat"] = out["lng"] = None
            out["geo_precision"] = "none"
        else:
            out["lat"], out["lng"] = c
            out["geo_precision"] = "approx"
    else:
        out["lat"], out["lng"] = round(float(out["lat"]), 4), round(float(out["lng"]), 4)
    out["title"] = (out.get("title") or "")[:160]
    return out


class AlertStore:
    """最近 N 条告警，按 alert_id 去重（后到的覆盖先到的，例如 USGS 修订震级）。"""

    def __init__(self, max_items: int = 200) -> None:
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._max = max_items

    def __len__(self) -> int:
        return len(self._items)

    def upsert(self, alert: dict) -> bool:
        """返回 True 表示是新告警（首次出现），False 表示更新已有告警。"""
        aid = alert["alert_id"]
        is_new = aid not in self._items
        if not is_new:
            del self._items[aid]
        self._items[aid] = alert
        while len(self._items) > self._max:
            self._items.popitem(last=False)
        return is_new

    def recent(self, limit: int = 50) -> list[dict]:
        items = sorted(self._items.values(), key=lambda a: a["event_time_ms"], reverse=True)
        return items[:limit]

    def count_since(self, since_ms: int) -> int:
        return sum(1 for a in self._items.values() if a["event_time_ms"] >= since_ms)
