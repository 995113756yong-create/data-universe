// 航位推算：已知位置、航向、地速，推算 dt 秒后的位置（大圆航线）
const R_EARTH = 6371000;
const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

export function project(lat: number, lng: number, headingDeg: number, speedMs: number, dtS: number): [number, number] {
  if (!Number.isFinite(headingDeg) || !Number.isFinite(speedMs) || speedMs <= 0 || dtS <= 0) return [lat, lng];
  const d = (speedMs * dtS) / R_EARTH;
  const h = headingDeg * D2R;
  const p1 = lat * D2R;
  const l1 = lng * D2R;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(h));
  const l2 = l1 + Math.atan2(Math.sin(h) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [p2 * R2D, normLng(l2 * R2D)];
}

export function normLng(lng: number): number {
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

/** 经度插值走最短方向（跨越 180° 经线时不会绕地球一圈） */
export function lerpLng(a: number, b: number, k: number): number {
  let d = b - a;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  return normLng(a + d * k);
}
