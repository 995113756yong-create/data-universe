import { describe, expect, it } from "vitest";
import { computeStats } from "./fps";

describe("computeStats", () => {
  it("稳定 60 帧", () => {
    const s = computeStats(new Array(60).fill(1000 / 60));
    expect(s.fps).toBeCloseTo(60, 0);
    expect(s.low1).toBeCloseTo(60, 0);
  });
  it("偶发卡顿拉低 1% Low，不明显影响平均值", () => {
    const frames = new Array(990).fill(16.67).concat(new Array(10).fill(50));
    const s = computeStats(frames);
    expect(s.fps).toBeGreaterThan(57);
    expect(s.low1).toBeLessThan(25);
  });
  it("空输入", () => {
    expect(computeStats([]).fps).toBe(0);
  });
});
