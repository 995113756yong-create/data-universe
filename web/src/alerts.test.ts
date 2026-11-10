import { describe, expect, it } from "vitest";
import { activeAlerts, alertText, mergeAlerts, MAX_ALERTS } from "./alerts";
import type { AlertItem } from "./protocol";

const T = 1_794_300_000_000;
const a = (id: string, t: number, over: Partial<AlertItem> = {}): AlertItem => ({
  alert_id: id, alert_type: "wiki_spike", source: "wiki", region: "Germany", window_start: "",
  event_time_ms: t, detected_ms: t + 100_000, value: 95, baseline_mean: 30.4, baseline_std: 6, zscore: 10.6,
  severity: "high", lat: 51, lng: 10, title: "", geo_precision: "approx", ...over,
});

describe("alerts", () => {
  it("merges by id and sorts newest first", () => {
    const m = mergeAlerts([a("x", T), a("y", T + 2)], [a("x", T, { value: 99 }), a("z", T + 1)]);
    expect(m.map((i) => i.alert_id)).toEqual(["y", "z", "x"]);
    expect(m[2].value).toBe(99);
  });
  it("caps size", () => {
    const many = Array.from({ length: MAX_ALERTS + 5 }, (_, i) => a(`a${i}`, T + i));
    expect(mergeAlerts([], many)).toHaveLength(MAX_ALERTS);
  });
  it("active = recent, located, not in the future", () => {
    const items = [a("old", T - 2 * 3600_000), a("ok", T - 60_000), a("nogeo", T, { lat: null }), a("future", T + 1000)];
    expect(activeAlerts(items, T).map((i) => i.alert_id)).toEqual(["ok"]);
  });
  it("formats text", () => {
    expect(alertText(a("x", T))).toBe("Germany 维基编辑激增：95 条/分，基线 30，z=10.6");
    const q = a("q", T, { alert_type: "quake_significant", value: 5.24, title: "M 5.2 - 120 km SE of Hualien, Taiwan" });
    expect(alertText(q)).toBe("M5.2 地震 · 120 km SE of Hualien, Taiwan");
  });
});
