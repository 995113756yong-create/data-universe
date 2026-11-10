import type { UniverseEngine } from "../globe/engine";
import { LAYERS, type Layer } from "../protocol";
import { store } from "../store";
import type { QuakeItem } from "./decode";

const MAX_QUAKES = 200;

function mergeQuakes(prev: QuakeItem[], add: QuakeItem[]): QuakeItem[] {
  const map = new Map(prev.map((q) => [q.id, q]));
  for (const q of add) map.set(q.id, q);
  return [...map.values()].sort((a, b) => b.eventMs - a.eventMs).slice(0, MAX_QUAKES);
}

/** 启动 Worker 并把数据分发给渲染引擎和 UI store。返回清理函数 */
export function startStream(engine: UniverseEngine): () => void {
  const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  const proto = location.protocol === "https:" ? "wss" : "ws";
  worker.postMessage({ k: "connect", url: `${proto}://${location.host}/ws` });

  worker.onmessage = (ev: MessageEvent) => {
    const m = ev.data;
    switch (m.k) {
      case "status":
        store.set({ conn: m.state, retryInMs: m.retryInMs });
        break;
      case "hello":
        if (Math.abs(m.clockSkewMs) > 2000) store.warn(`浏览器与服务器时钟相差 ${Math.round(m.clockSkewMs / 1000)} 秒，延迟数据可能不准`);
        break;
      case "wiki":
        engine.addWiki(m.pk);
        break;
      case "usgs":
        engine.addQuakes(m.items);
        store.set({ quakes: mergeQuakes(store.get().quakes, m.items) });
        break;
      case "flights":
        engine.upsertFlights(m.pk);
        break;
      case "batchinfo":
        store.set({ dropped: { wiki: store.get().dropped.wiki + (m.dropped.wiki ?? 0) }, cap: m.cap.wiki });
        break;
      case "metrics":
        store.set({ metrics: m.msg });
        break;
      case "net":
        store.set({ net: { bytesPerSec: m.bytesPerSec, msgsPerSec: m.msgsPerSec, lagP50: m.lagP50, lagP95: m.lagP95, lagN: m.lagN } });
        break;
      case "warn":
        store.warn(m.msg);
        break;
    }
  };

  let lastLayers = store.get().layers;
  const unsub = store.subscribe(() => {
    const layers = store.get().layers;
    if (layers === lastLayers) return;
    lastLayers = layers;
    const on = LAYERS.filter((l: Layer) => layers[l]);
    worker.postMessage({ k: "subscribe", layers: on });
  });

  // 每 2 秒上报渲染帧率，网关据此调整推送上限（背压）
  const loadTimer = window.setInterval(() => {
    const fps = engine.meter.current.fps;
    if (fps > 0) worker.postMessage({ k: "load", fps });
  }, 2000);

  return () => {
    window.clearInterval(loadTimer);
    unsub();
    worker.terminate();
  };
}
