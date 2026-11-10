// 与 three-globe 的 polar2Cartesian 保持一致（地球半径 100）。GlobeView 启动时会用 globe.getCoords 自检
export const GLOBE_RADIUS = 100;
const D2R = Math.PI / 180;

export function toXYZ(lat: number, lng: number, relAlt = 0, out: Float32Array | number[] = [0, 0, 0], o = 0) {
  const phi = (90 - lat) * D2R;
  const theta = (90 - lng) * D2R;
  const r = GLOBE_RADIUS * (1 + relAlt);
  const s = Math.sin(phi);
  out[o] = r * s * Math.cos(theta);
  out[o + 1] = r * Math.cos(phi);
  out[o + 2] = r * s * Math.sin(theta);
  return out;
}

/** 由 seed ∈ [0,1) 生成落在半径 radiusDeg 圆盘内的稳定偏移（面积均匀） */
export function jitter(lat: number, lng: number, seed: number, radiusDeg: number): [number, number] {
  const angle = seed * Math.PI * 2;
  const frac = (seed * 7919.123) % 1;
  const r = Math.sqrt(frac) * radiusDeg;
  const jl = Math.max(-85, Math.min(85, lat + r * Math.sin(angle)));
  const cos = Math.max(0.2, Math.cos(jl * D2R));
  let jg = lng + (r * Math.cos(angle)) / cos;
  if (jg > 180) jg -= 360;
  if (jg < -180) jg += 360;
  return [jl, jg];
}
