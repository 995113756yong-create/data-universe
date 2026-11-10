import type { AlertItem } from "./protocol";

export const MAX_ALERTS = 100;
export const ACTIVE_MS = 60 * 60 * 1000; // 地球上脉冲显示最近 1 小时的告警

/** 按 alert_id 合并（后到的覆盖），按事件时间倒序，最多 MAX_ALERTS 条 */
export function mergeAlerts(prev: AlertItem[], add: AlertItem[]): AlertItem[] {
  const map = new Map(prev.map((a) => [a.alert_id, a]));
  for (const a of add) map.set(a.alert_id, a);
  return [...map.values()].sort((a, b) => b.event_time_ms - a.event_time_ms).slice(0, MAX_ALERTS);
}

export function activeAlerts(items: AlertItem[], now: number): AlertItem[] {
  return items.filter((a) => a.lat !== null && a.lng !== null && now - a.event_time_ms <= ACTIVE_MS && a.event_time_ms <= now);
}

export function alertText(a: AlertItem): string {
  if (a.alert_type === "wiki_spike") {
    const base = a.baseline_mean === null ? "" : `，基线 ${Math.round(a.baseline_mean)}`;
    const z = a.zscore === null ? "" : `，z=${a.zscore.toFixed(1)}`;
    return `${a.region} 维基编辑激增：${Math.round(a.value)} 条/分${base}${z}`;
  }
  const place = a.title.replace(/^M\s*-?[\d.?]+\s*-\s*/, "") || a.region;
  return `M${a.value.toFixed(1)} 地震 · ${place}`;
}

export const SEVERITY_COLOR: Record<AlertItem["severity"], string> = {
  medium: "#ffb020",
  high: "#ff6b3d",
  critical: "#ff2d55",
};
