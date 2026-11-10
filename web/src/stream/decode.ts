// 纯函数：把网关的 JSON 行转换成 TypedArray，便于 Worker -> 主线程零拷贝传输
import { F, FlightRow, P, PointRow } from "../protocol";

export interface PointPacket {
  n: number;
  lat: Float32Array;
  lng: Float32Array;
  weight: Float32Array;
  seed: Float32Array; // 由 id 哈希得到的 [0,1) 随机数，用于近似坐标的稳定抖动
  ageS: Float32Array; // 到达浏览器时事件已经过去的秒数（快照数据会比较大）
  region: string[];
}

export interface QuakeItem { id: string; lat: number; lng: number; mag: number; eventMs: number; title: string; url: string; region: string }

export interface FlightPacket {
  n: number;
  ids: string[];
  lat: Float32Array;
  lng: Float32Array;
  heading: Float32Array; // NaN 表示未知
  velocity: Float32Array; // NaN 表示未知
  altitude: Float32Array;
  eventMs: Float64Array;
  callsign: string[];
}

/** FNV-1a 32 位哈希 -> [0,1) */
export function hash01(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 4294967296;
}

export function decodePoints(rows: PointRow[], nowMs: number): PointPacket {
  const n = rows.length;
  const pk: PointPacket = {
    n,
    lat: new Float32Array(n),
    lng: new Float32Array(n),
    weight: new Float32Array(n),
    seed: new Float32Array(n),
    ageS: new Float32Array(n),
    region: new Array(n),
  };
  for (let i = 0; i < n; i++) {
    const r = rows[i];
    pk.lat[i] = r[P.lat];
    pk.lng[i] = r[P.lng];
    pk.weight[i] = r[P.weight];
    pk.seed[i] = hash01(r[P.id]);
    pk.ageS[i] = Math.max(0, (nowMs - r[P.eventMs]) / 1000);
    pk.region[i] = r[P.region];
  }
  return pk;
}

export function decodeQuakes(rows: PointRow[]): QuakeItem[] {
  return rows.map((r) => ({
    id: r[P.id], lat: r[P.lat], lng: r[P.lng], mag: r[P.weight], eventMs: r[P.eventMs],
    title: r[P.title], url: r[P.url], region: r[P.region],
  }));
}

export function decodeFlights(rows: FlightRow[]): FlightPacket {
  const n = rows.length;
  const pk: FlightPacket = {
    n,
    ids: new Array(n),
    lat: new Float32Array(n),
    lng: new Float32Array(n),
    heading: new Float32Array(n),
    velocity: new Float32Array(n),
    altitude: new Float32Array(n),
    eventMs: new Float64Array(n),
    callsign: new Array(n),
  };
  for (let i = 0; i < n; i++) {
    const r = rows[i];
    pk.ids[i] = r[F.icao24];
    pk.lat[i] = r[F.lat];
    pk.lng[i] = r[F.lng];
    pk.heading[i] = r[F.heading] ?? NaN;
    pk.velocity[i] = r[F.velocity] ?? NaN;
    pk.altitude[i] = r[F.altitude] ?? 0;
    pk.eventMs[i] = r[F.eventMs];
    pk.callsign[i] = r[F.callsign];
  }
  return pk;
}

/** 浏览器侧端到端延迟样本：收到时刻 - 采集时刻（ms） */
export function ingestLags(rows: { [k: number]: unknown }[], ingestIdx: number, recvMs: number): number[] {
  const out: number[] = [];
  for (const r of rows) {
    const v = r[ingestIdx];
    if (typeof v === "number" && v > 0) out.push(recvMs - v);
  }
  return out;
}

export function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return NaN;
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}
