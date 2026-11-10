import { describe, expect, it } from "vitest";
import type { PointRow } from "../protocol";
import type { Manifest } from "./format";
import { chunkIndex, metricsAt, ReplayClock, timeRange } from "./timeline";

const S = 1_794_300_000_000 - (1_794_300_000_000 % 60_000);

describe("ReplayClock", () => {
  it("advances with speed, pauses, seeks and clamps", () => {
    let real = 1000;
    const c = new ReplayClock(S, S + 600_000, () => real);
    expect(c.now()).toBe(S);
    c.play();
    real += 1000;
    expect(c.now()).toBe(S + 1000);
    c.setSpeed(60);
    real += 1000;
    expect(c.now()).toBe(S + 61_000);
    c.pause();
    real += 5000;
    expect(c.now()).toBe(S + 61_000);
    c.seek(S + 10_000_000);
    expect(c.now()).toBe(S + 600_000);
    expect(c.ended).toBe(true);
    c.play(); // 播完再播：回到开头
    expect(c.now()).toBe(S);
  });
});

describe("timeRange", () => {
  const rows = [1, 2, 2, 3, 5, 8];
  it("returns (from, to] slice", () => {
    expect(timeRange(rows, (x) => x, 2, 5)).toEqual([3, 5]);
    expect(timeRange(rows, (x) => x, 0, 100)).toEqual([0, 6]);
    expect(timeRange(rows, (x) => x, 8, 9)).toEqual([6, 6]);
    expect(timeRange([], (x: number) => x, 0, 1)).toEqual([0, 0]);
  });
});

const q = (t: number, mag: number): PointRow => ["q", 0, 0, mag, t, t, "Japan", "", ""];

function manifest(): Manifest {
  return {
    v: 1, protocol: 1, id: "r", title: "", created_ms: S, start_ms: S, end_ms: S + 3600_000, chunk_ms: 60_000,
    sampling: { wiki_per_min: 1, flight_permille: 1, flight_step_s: 1 },
    chunks: Array.from({ length: 60 }, (_, i) => ({ i, t0: S + i * 60_000, file: "", n: { wiki: 0, opensky: 0 } })),
    quakes: [q(S - 25 * 3600_000, 6.0), q(S - 3600_000, 4.2), q(S + 120_000, 5.1), q(S + 999_999, 7)],
    alerts: [],
    agg: [
      [S, "wiki", "Germany", 100],
      [S, "wiki", "Japan", 20],
      [S + 60_000, "wiki", "Germany", 300],
      [S + 120_000, "wiki", "Germany", 999], // v 之后，不计
      [S + 60_000, "usgs", "Unknown", 2],
    ],
    qa: [],
  };
}

describe("metricsAt", () => {
  it("synthesizes panel metrics at virtual time", () => {
    const m = metricsAt(manifest(), S + 150_000, 42);
    expect(m.last_minute.wiki).toBe(300);
    expect(m.eps.wiki).toBe(5);
    expect(m.flights_tracked).toBe(42);
    expect(m.trend).toHaveLength(3);
    expect(m.trend).toContainEqual({ ts: S, source: "wiki", cnt: 120 });
    expect(m.trend).toContainEqual({ ts: S + 60_000, source: "wiki", cnt: 300 });
    expect(m.trend).toContainEqual({ ts: S + 60_000, source: "usgs", cnt: 2 });
    expect(m.top_regions![0]).toEqual({ source: "wiki", region: "Germany", cnt: 400 });
    expect(m.top_regions!.some((r) => r.region === "Unknown")).toBe(false);
    expect(m.quakes_24h).toEqual({ count: 2, max_mag: 5.1 });
  });
});

describe("chunkIndex", () => {
  it("clamps", () => {
    const m = manifest();
    expect(chunkIndex(m, S - 1)).toBe(0);
    expect(chunkIndex(m, S + 61_000)).toBe(1);
    expect(chunkIndex(m, S + 99 * 3600_000)).toBe(59);
  });
});
