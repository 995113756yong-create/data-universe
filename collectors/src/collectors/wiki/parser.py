"""Wikimedia recentchange 事件 -> raw.wiki 消息。纯函数，不做 IO。契约见 docs/contracts.md。"""

from __future__ import annotations

import json
from pathlib import Path

RAW_WIKI_FIELDS = (
    "event_id",
    "wiki",
    "lang",
    "change_type",
    "namespace",
    "title",
    "bot",
    "bytes_delta",
    "event_time_ms",
    "ingest_time_ms",
    "url",
    "region",
    "lat",
    "lng",
)

ALLOWED_TYPES = frozenset({"edit", "new"})


def load_lang_region(path: str | Path | None = None) -> dict[str, dict]:
    path = Path(path) if path else Path(__file__).with_name("lang_region.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def parse_event(evt: dict, mapping: dict[str, dict], ingest_time_ms: int) -> dict | None:
    """被过滤或无法解析返回 None。过滤顺序：canary -> 非 wikipedia -> 非 edit/new。"""
    if not isinstance(evt, dict):
        return None
    meta = evt.get("meta") or {}
    if meta.get("domain") == "canary":
        return None
    server = evt.get("server_name") or ""
    if not server.endswith(".wikipedia.org"):
        return None
    change_type = evt.get("type")
    if change_type not in ALLOWED_TYPES:
        return None

    event_id = meta.get("id")
    ts = evt.get("timestamp")
    if not event_id or ts is None:
        return None
    try:
        event_time_ms = int(ts) * 1000
    except (TypeError, ValueError):
        return None

    bytes_delta = None
    length = evt.get("length")
    if isinstance(length, dict) and length.get("new") is not None:
        try:
            bytes_delta = int(length["new"]) - int(length.get("old") or 0)
        except (TypeError, ValueError):
            bytes_delta = None

    lang = server.split(".", 1)[0]
    geo = mapping.get(lang)
    try:
        namespace = int(evt.get("namespace") or 0)
    except (TypeError, ValueError):
        namespace = 0

    # 注意：刻意不输出 user 字段，不传播用户名。
    return {
        "event_id": str(event_id),
        "wiki": evt.get("wiki") or "",
        "lang": lang,
        "change_type": change_type,
        "namespace": namespace,
        "title": evt.get("title") or "",
        "bot": bool(evt.get("bot", False)),
        "bytes_delta": bytes_delta,
        "event_time_ms": event_time_ms,
        "ingest_time_ms": int(ingest_time_ms),
        "url": meta.get("uri") or "",
        "region": geo["region"] if geo else "Unknown",
        "lat": float(geo["lat"]) if geo else None,
        "lng": float(geo["lng"]) if geo else None,
    }
