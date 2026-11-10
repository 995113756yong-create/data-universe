// 网关 -> 浏览器协议（与 gateway/src/gateway/protocol.py、docs/contracts.md 保持一致）
export const PROTOCOL_VERSION = 1;
export type Layer = "wiki" | "usgs" | "opensky";
export const LAYERS: Layer[] = ["wiki", "usgs", "opensky"];

// 点图层行：[id, lat, lng, weight, event_ms, ingest_ms, region, title, url]
export const P = { id: 0, lat: 1, lng: 2, weight: 3, eventMs: 4, ingestMs: 5, region: 6, title: 7, url: 8 } as const;
export type PointRow = [string, number, number, number, number, number, string, string, string];

// 航班行：[icao24, lat, lng, heading_deg, velocity_ms, altitude_m, event_ms, ingest_ms, callsign, origin_country]
export const F = {
  icao24: 0, lat: 1, lng: 2, heading: 3, velocity: 4, altitude: 5, eventMs: 6, ingestMs: 7, callsign: 8, country: 9,
} as const;
export type FlightRow = [string, number, number, number | null, number | null, number, number, number, string, string];

export interface HelloMsg { t: "hello"; v: number; server_ms: number; tick_ms: number; layers: Layer[] }
export interface SnapshotMsg { t: "snapshot"; layer: Layer; rows: PointRow[] | FlightRow[] }
export interface BatchMsg {
  t: "batch";
  server_ms: number;
  rows: Partial<{ wiki: PointRow[]; usgs: PointRow[]; opensky: FlightRow[] }>;
  dropped: Partial<Record<Layer, number>>;
  cap: { wiki: number };
  pending: { opensky: number };
}
export interface Quantiles { p50: number; p95: number; n: number }
export interface MetricsMsg {
  t: "metrics";
  server_ms: number;
  eps: Record<Layer, number>;
  last_minute: Record<Layer, number>;
  lag_ms: Record<Layer, Quantiles | null>;
  flights_tracked: number;
  sources: Record<Layer, { status: "ok" | "stale" | "waiting"; event_ms?: number; recv_ms?: number }>;
  clients: number;
  kafka_ok: boolean;
  clickhouse_ok: boolean;
  trend?: { ts: number; source: Layer; cnt: number }[];
  top_regions?: { source: Layer; region: string; cnt: number }[];
  quakes_24h?: { count: number; max_mag: number };
}
export interface WarnMsg { t: "warn"; msg: string }
export type ServerMsg = HelloMsg | SnapshotMsg | BatchMsg | MetricsMsg | WarnMsg;
