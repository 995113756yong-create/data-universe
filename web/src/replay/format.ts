// 回放包格式（与 gateway/src/gateway/replay_export.py、docs/contracts.md「回放包」一致）
import type { AlertItem, AskResult, FlightRow, PointRow } from "../protocol";

export const MANIFEST_VERSION = 1;

export interface ReplayIndex {
  replays: { id: string; title: string; start_ms: number; end_ms: number; bytes: number }[];
}

export interface ChunkRef { i: number; t0: number; file: string; n: { wiki: number; opensky: number } }

export interface Manifest {
  v: number;
  protocol: number;
  id: string;
  title: string;
  created_ms: number;
  start_ms: number;
  end_ms: number;
  chunk_ms: number;
  sampling: { wiki_per_min: number; flight_permille: number; flight_step_s: number };
  chunks: ChunkRef[];
  quakes: PointRow[];
  alerts: AlertItem[];
  agg: [number, "wiki" | "usgs", string, number][]; // [分钟起点 ms, source, region, cnt]
  qa: AskResult[];
}

export interface Chunk { t0: number; wiki: PointRow[]; opensky: FlightRow[] }

function isGzip(b: Uint8Array) {
  return b.length > 2 && b[0] === 0x1f && b[1] === 0x8b;
}

/** 读取 JSON；.gz 文件用浏览器原生 DecompressionStream 解压。
 *  部分静态服务器会对 .gz 自动加 Content-Encoding，浏览器已解压过，所以按魔数判断而不是按扩展名。 */
export async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url}: HTTP ${resp.status}`);
  const buf = new Uint8Array(await resp.arrayBuffer());
  let text: string;
  if (isGzip(buf)) {
    if (typeof DecompressionStream === "undefined") throw new Error("浏览器不支持 DecompressionStream，请使用新版 Chrome / Edge / Firefox / Safari");
    const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(buf);
  }
  return JSON.parse(text) as T;
}
