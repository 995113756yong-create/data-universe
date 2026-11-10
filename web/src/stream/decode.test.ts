import { describe, expect, it } from "vitest";
import type { FlightRow, PointRow } from "../protocol";
import { decodeFlights, decodePoints, decodeQuakes, hash01, ingestLags, percentile } from "./decode";

const wiki: PointRow = ["w1", 39.8, -98.6, 250, 1_000_000, 1_000_100, "United States", "Page", "https://x"];
const flight: FlightRow = ["abc123", 45.1, 5.2, null, 225.8, 10676, 2_000_000, 2_003_000, "AFR1", "France"];

describe("decode", () => {
  it("hash01 稳定且在 [0,1)", () => {
    expect(hash01("w1")).toBe(hash01("w1"));
    for (const s of ["", "a", "11111111-1111", "zzzzzzzzzzzzzzzzzz"]) {
      const v = hash01(s);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
    expect(hash01("a")).not.toBe(hash01("b"));
  });

  it("decodePoints 计算到达时已过去的秒数", () => {
    const pk = decodePoints([wiki], 1_005_000);
    expect(pk.n).toBe(1);
    expect(pk.lat[0]).toBeCloseTo(39.8, 4);
    expect(pk.ageS[0]).toBeCloseTo(4, 5);
    expect(pk.region[0]).toBe("United States");
    expect(decodePoints([wiki], 0).ageS[0]).toBe(0); // 时钟偏差导致的负数截断为 0
  });

  it("decodeFlights 未知航向记为 NaN", () => {
    const pk = decodeFlights([flight]);
    expect(pk.ids[0]).toBe("abc123");
    expect(Number.isNaN(pk.heading[0])).toBe(true);
    expect(pk.velocity[0]).toBeCloseTo(225.8, 3);
    expect(pk.eventMs[0]).toBe(2_000_000);
  });

  it("decodeQuakes 字段映射", () => {
    expect(decodeQuakes([wiki])[0]).toMatchObject({ id: "w1", mag: 250, eventMs: 1_000_000, url: "https://x" });
  });

  it("延迟与分位数", () => {
    expect(ingestLags([wiki, ["x", 0, 0, 0, 0, 0, "", "", ""]], 5, 1_000_600)).toEqual([500]);
    expect(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95)).toBe(10);
    expect(Number.isNaN(percentile([], 0.5))).toBe(true);
  });
});
