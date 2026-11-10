/// <reference lib="webworker" />
// WebSocket 与 JSON 解析放在 Worker，主线程只负责渲染
import { BatchMsg, FlightRow, Layer, P, PointRow, ServerMsg } from "../protocol";
import { decodeFlights, decodePoints, decodeQuakes, ingestLags, percentile } from "./decode";

declare const self: DedicatedWorkerGlobalScope;

let ws: WebSocket | null = null;
let url = "";
let layers: Layer[] = ["wiki", "usgs", "opensky"];
let retry = 0;
let bytes = 0;
let msgs = 0;
let lags: number[] = [];

function post(msg: unknown, transfer: Transferable[] = []) {
  self.postMessage(msg, transfer);
}

function handlePoints(layer: Layer, rows: PointRow[], snapshot: boolean, now: number) {
  if (!rows.length) return;
  if (layer === "usgs") {
    post({ k: "usgs", items: decodeQuakes(rows), snapshot });
    return;
  }
  const pk = decodePoints(rows, now);
  post({ k: "wiki", pk, snapshot }, [pk.lat.buffer, pk.lng.buffer, pk.weight.buffer, pk.seed.buffer, pk.ageS.buffer]);
}

function handleFlights(rows: FlightRow[], snapshot: boolean) {
  if (!rows.length) return;
  const pk = decodeFlights(rows);
  post({ k: "flights", pk, snapshot }, [
    pk.lat.buffer, pk.lng.buffer, pk.heading.buffer, pk.velocity.buffer, pk.altitude.buffer, pk.eventMs.buffer,
  ]);
}

function onMessage(ev: MessageEvent<string>) {
  const now = Date.now();
  bytes += ev.data.length;
  msgs += 1;
  let m: ServerMsg;
  try {
    m = JSON.parse(ev.data);
  } catch {
    return;
  }
  switch (m.t) {
    case "hello":
      post({ k: "hello", msg: m, clockSkewMs: now - m.server_ms });
      break;
    case "snapshot":
      if (m.layer === "opensky") handleFlights(m.rows as FlightRow[], true);
      else handlePoints(m.layer, m.rows as PointRow[], true, now);
      break;
    case "batch": {
      const b = m as BatchMsg;
      if (b.rows.wiki) {
        lags.push(...ingestLags(b.rows.wiki, P.ingestMs, now));
        handlePoints("wiki", b.rows.wiki, false, now);
      }
      if (b.rows.usgs) handlePoints("usgs", b.rows.usgs, false, now);
      if (b.rows.opensky) {
        // 航班延迟主要来自 OpenSky 轮询间隔，不计入链路延迟统计
        handleFlights(b.rows.opensky, false);
      }
      post({ k: "batchinfo", dropped: b.dropped, cap: b.cap, pending: b.pending });
      break;
    }
    case "metrics":
      post({ k: "metrics", msg: m });
      break;
    case "alerts":
      post({ k: "alerts", items: m.rows, live: false });
      break;
    case "alert":
      post({ k: "alerts", items: [m.alert], live: m.new });
      break;
    case "warn":
      post({ k: "warn", msg: m.msg });
      break;
  }
}

function connect() {
  post({ k: "status", state: "connecting" });
  ws = new WebSocket(url);
  ws.onopen = () => {
    retry = 0;
    post({ k: "status", state: "open" });
    ws?.send(JSON.stringify({ t: "subscribe", layers }));
  };
  ws.onmessage = onMessage;
  ws.onclose = () => {
    const delay = Math.min(30000, 1000 * 2 ** retry) * (0.5 + Math.random() / 2);
    retry += 1;
    post({ k: "status", state: "closed", retryInMs: Math.round(delay) });
    setTimeout(connect, delay);
  };
  ws.onerror = () => ws?.close();
}

// 每秒汇报一次网络统计
setInterval(() => {
  const sorted = lags.sort((a, b) => a - b);
  post({ k: "net", bytesPerSec: bytes, msgsPerSec: msgs, lagP50: percentile(sorted, 0.5), lagP95: percentile(sorted, 0.95), lagN: sorted.length });
  bytes = 0;
  msgs = 0;
  if (lags.length > 3000) lags = lags.slice(-1500);
}, 1000);

self.onmessage = (ev: MessageEvent) => {
  const m = ev.data;
  if (m.k === "connect") {
    url = m.url;
    connect();
  } else if (m.k === "subscribe") {
    layers = m.layers;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: "subscribe", layers }));
  } else if (m.k === "load") {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ t: "load", fps: m.fps }));
  }
};
