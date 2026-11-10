import { describe, expect, it } from "vitest";
import { GLOBE_RADIUS, jitter, toXYZ } from "./coords";
import { lerpLng, normLng, project } from "./deadReckoning";
import { RingIndex } from "./ring";

describe("toXYZ（需与 three-globe polar2Cartesian 一致）", () => {
  it("北极在 +Y，(0,0) 在 +Z，(0,90) 在 +X", () => {
    const n = toXYZ(90, 0);
    expect(n[1]).toBeCloseTo(GLOBE_RADIUS, 6);
    const o = toXYZ(0, 0);
    expect(o[0]).toBeCloseTo(0, 6);
    expect(o[2]).toBeCloseTo(GLOBE_RADIUS, 6);
    const e = toXYZ(0, 90);
    expect(e[0]).toBeCloseTo(GLOBE_RADIUS, 6);
  });
  it("高度按半径比例放大", () => {
    const p = toXYZ(30, 60, 0.1);
    expect(Math.hypot(p[0], p[1], p[2])).toBeCloseTo(GLOBE_RADIUS * 1.1, 4);
  });
});

describe("jitter", () => {
  it("稳定、在半径内、经度归一化", () => {
    for (let i = 0; i < 200; i++) {
      const seed = i / 200;
      const [la, lo] = jitter(40, 179, seed, 5);
      expect(jitter(40, 179, seed, 5)).toEqual([la, lo]);
      expect(Math.abs(la - 40)).toBeLessThanOrEqual(5.0001);
      expect(lo).toBeGreaterThanOrEqual(-180);
      expect(lo).toBeLessThanOrEqual(180);
    }
  });
});

describe("航位推算", () => {
  it("向北飞 111.2 km ≈ 纬度 +1°", () => {
    const [la, lo] = project(0, 0, 0, 111_195, 1);
    expect(la).toBeCloseTo(1, 2);
    expect(lo).toBeCloseTo(0, 6);
  });
  it("赤道向东飞 ≈ 经度 +1°", () => {
    const [la, lo] = project(0, 0, 90, 111_195, 1);
    expect(la).toBeCloseTo(0, 4);
    expect(lo).toBeCloseTo(1, 2);
  });
  it("跨越 180° 经线后归一化", () => {
    const [, lo] = project(0, 179.9, 90, 111_195, 1);
    expect(lo).toBeLessThan(-178);
  });
  it("速度/航向未知时不动", () => {
    expect(project(10, 20, NaN, 200, 60)).toEqual([10, 20]);
    expect(project(10, 20, 90, NaN, 60)).toEqual([10, 20]);
    expect(project(10, 20, 90, 200, 0)).toEqual([10, 20]);
  });
  it("lerpLng 走最短方向", () => {
    expect(lerpLng(179, -179, 0.5)).toBeCloseTo(180 - 360, 6);
    expect(normLng(190)).toBeCloseTo(-170, 6);
  });
});

describe("RingIndex", () => {
  it("满了覆盖最旧的", () => {
    const r = new RingIndex(3);
    expect([r.take(), r.take(), r.take(), r.take()]).toEqual([0, 1, 2, 0]);
    expect(r.size).toBe(3);
    expect(() => new RingIndex(0)).toThrow();
  });
});
