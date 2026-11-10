import { mergeAlerts } from "../alerts";
import type { UniverseEngine } from "../globe/engine";
import type { AlertItem } from "../protocol";
import { store } from "../store";
import type { QuakeItem } from "./decode";

const MAX_QUAKES = 200;
const TOAST_MS = 9000;

export function mergeQuakes(prev: QuakeItem[], add: QuakeItem[]): QuakeItem[] {
  const map = new Map(prev.map((q) => [q.id, q]));
  for (const q of add) map.set(q.id, q);
  return [...map.values()].sort((a, b) => b.eventMs - a.eventMs).slice(0, MAX_QUAKES);
}

/** 实时（Worker）与回放（ReplayPlayer）共用的数据出口：渲染引擎 + UI store */
export function pushQuakes(engine: UniverseEngine, items: QuakeItem[]) {
  if (!items.length) return;
  engine.addQuakes(items);
  store.set({ quakes: mergeQuakes(store.get().quakes, items) });
}

/** live=true 表示刚发生的新告警：弹出提示卡片；快照里的旧告警只进列表 */
export function pushAlerts(engine: UniverseEngine, items: AlertItem[], live: boolean) {
  if (!items.length) return;
  const alerts = mergeAlerts(store.get().alerts, items);
  const patch: Partial<ReturnType<typeof store.get>> = { alerts };
  if (live) {
    const ids = new Set(items.map((a) => a.alert_id));
    patch.toasts = [...items, ...store.get().toasts.filter((t) => !ids.has(t.alert_id))].slice(0, 3);
    window.setTimeout(() => {
      store.set({ toasts: store.get().toasts.filter((t) => !ids.has(t.alert_id)) });
    }, TOAST_MS);
  }
  store.set(patch);
  engine.setAlerts(alerts);
}
