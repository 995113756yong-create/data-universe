// 回放的纯逻辑（无 DOM / WebGL 依赖，vitest 覆盖）
import { F, P, type FlightRow, type Layer, type MetricsMsg, type PointRow } from "../protocol";
import type { Manifest } from "./format";

/** 虚拟时钟：v = 锚点虚拟时间 + (真实时间 - 锚点真实时间) × 倍速，到终点停止 */
export class ReplayClock {
  private anchorV: number;
  private anchorR: number;
  speed = 1;
  playing = false;

  constructor(
    readonly startMs: number,
    readonly endMs: number,
    private readonly realNow: () => number = () => performance.now(),
  ) {
    this.anchorV = startMs;
    this.anchorR = realNow();
  }

  now(): number {
    if (!this.playing) return this.anchorV;
    return Math.min(this.endMs, this.anchorV + (this.realNow() - this.anchorR) * this.speed);
  }

  play() {
    if (this.playing) return;
    if (this.anchorV >= this.endMs) this.anchorV = this.startMs; // 播完再点播放：从头开始
    this.anchorR = this.realNow();
    this.playing = true;
  }

  pause() {
    this.anchorV = this.now();
    this.playing = false;
  }

  setSpeed(s: number) {
    this.anchorV = this.now();
    this.anchorR = this.realNow();
    this.speed = s;
  }

  seek(v: number) {
    this.anchorV = Math.max(this.startMs, Math.min(this.endMs, v));
    this.anchorR = this.realNow();
  }

  get ended() {
    return this.now() >= this.endMs;
  }
}

/** 已按时间升序的数组里，返回满足 from < t <= to 的下标区间 [lo, hi) */
export function timeRange<T>(rows: T[], t: (r: T) => number, from: number, to: number): [number, number] {
  const bound = (x: number) => {
    let lo = 0;
    let hi = rows.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (t(rows[mid]) <= x) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };
  return [bound(from), bound(to)];
}

export const pointTime = (r: PointRow) => r[P.eventMs];
export const flightTime = (r: FlightRow) => r[F.eventMs];

export function chunkIndex(m: Pick<Manifest, "start_ms" | "chunk_ms" | "chunks">, v: number): number {
  const i = Math.floor((v - m.start_ms) / m.chunk_ms);
  return Math.max(0, Math.min(m.chunks.length - 1, i));
}

/** 把事件时间平移到 v 所在的「真实」时间：回放里 ingest_ms 不参与延迟统计，原样保留即可 */
export function alertShowTime(a: { detected_ms: number; event_time_ms: number }): number {
  return a.detected_ms > 0 ? a.detected_ms : a.event_time_ms;
}

const MIN = 60_000;

/** 用回放包里的分钟聚合，合成与实时网关同结构的面板指标 */
export function metricsAt(m: Manifest, v: number, flightsTracked: number): MetricsMsg {
  const lastMin = Math.floor(v / MIN) * MIN - MIN; // 最近一个完整分钟
  const lastMinute: Record<Layer, number> = { wiki: 0, usgs: 0, opensky: 0 };
  const trendMap = new Map<string, { ts: number; source: Layer; cnt: number }>();
  const regionMap = new Map<string, { source: Layer; region: string; cnt: number }>();
  for (const [ts, source, region, cnt] of m.agg) {
    if (ts > v - MIN) continue; // 还没「发生」完的分钟不计
    if (ts === lastMin) lastMinute[source] += cnt;
    if (ts > v - 31 * MIN) {
      const k = `${ts}|${source}`;
      const e = trendMap.get(k) ?? { ts, source, cnt: 0 };
      e.cnt += cnt;
      trendMap.set(k, e);
    }
    if (ts > v - 11 * MIN && region !== "Unknown") {
      const k = `${source}|${region}`;
      const e = regionMap.get(k) ?? { source, region, cnt: 0 };
      e.cnt += cnt;
      regionMap.set(k, e);
    }
  }
  let qCount = 0;
  let qMax = 0;
  for (const q of m.quakes) {
    const t = q[P.eventMs];
    if (t <= v && t > v - 24 * 3600_000) {
      qCount++;
      qMax = Math.max(qMax, q[P.weight]);
    }
  }
  const src = { status: "ok" as const, event_ms: v, recv_ms: v };
  return {
    t: "metrics",
    server_ms: v,
    eps: { wiki: lastMinute.wiki / 60, usgs: lastMinute.usgs / 60, opensky: 0 },
    last_minute: lastMinute,
    lag_ms: { wiki: null, usgs: null, opensky: null },
    flights_tracked: flightsTracked,
    sources: { wiki: src, usgs: src, opensky: src },
    clients: 0,
    kafka_ok: true,
    clickhouse_ok: true,
    trend: [...trendMap.values()].sort((a, b) => a.ts - b.ts),
    top_regions: [...regionMap.values()].sort((a, b) => b.cnt - a.cnt).slice(0, 10),
    quakes_24h: { count: qCount, max_mag: qMax },
  };
}
