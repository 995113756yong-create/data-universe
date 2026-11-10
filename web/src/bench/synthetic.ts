import type { UniverseEngine } from "../globe/engine";
import type { FlightPacket, PointPacket } from "../stream/decode";
import { store, type BenchResult } from "../store";

// 压测模式（?bench=1）：不连网关，注入 2 万维基点 + 1 万架航班，自转状态下录 30 秒帧率
export const BENCH = { wikiPoints: 20000, flights: 10000, wikiPerSecond: 1000, warmupS: 3, durationS: 30, passFps: 55, passLow1: 45 };

function rng(seed: number) {
  let s = seed;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

function randomPoints(n: number, r: () => number, maxAgeS: number): PointPacket {
  const pk: PointPacket = {
    n, lat: new Float32Array(n), lng: new Float32Array(n), weight: new Float32Array(n),
    seed: new Float32Array(n), ageS: new Float32Array(n), region: new Array(n).fill("Bench"),
  };
  for (let i = 0; i < n; i++) {
    pk.lat[i] = (Math.asin(r() * 2 - 1) * 180) / Math.PI;
    pk.lng[i] = r() * 360 - 180;
    pk.weight[i] = r() * 2000;
    pk.seed[i] = r();
    pk.ageS[i] = r() * maxAgeS;
  }
  return pk;
}

function randomFlights(n: number, r: () => number, nowMs: number): FlightPacket {
  const pk: FlightPacket = {
    n, ids: [], lat: new Float32Array(n), lng: new Float32Array(n), heading: new Float32Array(n),
    velocity: new Float32Array(n), altitude: new Float32Array(n), eventMs: new Float64Array(n), callsign: [],
  };
  for (let i = 0; i < n; i++) {
    pk.ids.push(`bench${i}`);
    pk.callsign.push(`BCH${i}`);
    pk.lat[i] = r() * 120 - 60;
    pk.lng[i] = r() * 360 - 180;
    pk.heading[i] = r() * 360;
    pk.velocity[i] = 180 + r() * 80;
    pk.altitude[i] = r() * 12000;
    pk.eventMs[i] = nowMs;
  }
  return pk;
}

const sleep = (ms: number) => new Promise((res) => setTimeout(res, ms));

export async function runBench(engine: UniverseEngine): Promise<BenchResult> {
  const r = rng(7);
  engine.addWiki(randomPoints(BENCH.wikiPoints, r, 500));
  engine.upsertFlights(randomFlights(BENCH.flights, r, Date.now()));
  let running = true;
  const feeder = (async () => {
    let tick = 0;
    while (running) {
      engine.addWiki(randomPoints(BENCH.wikiPerSecond / 5, r, 0)); // 模拟网关每 200ms 一包
      if (++tick % 50 === 0) engine.upsertFlights(randomFlights(BENCH.flights, rng(tick), Date.now())); // 模拟每 10s 一次轮询
      await sleep(200);
    }
  })();

  store.set({ bench: { phase: "warmup" } });
  await sleep(BENCH.warmupS * 1000);
  store.set({ bench: { phase: "recording" } });
  engine.meter.startRecording();
  await sleep(BENCH.durationS * 1000);
  const stats = engine.meter.stopRecording();
  running = false;
  await feeder;

  const counts = engine.counts();
  const result: BenchResult = {
    ...stats,
    wiki_points: counts.wiki,
    flights: counts.opensky,
    dpr: window.devicePixelRatio,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    user_agent: navigator.userAgent,
    pass: stats.fps >= BENCH.passFps && stats.low1 >= BENCH.passLow1 && counts.wiki >= BENCH.wikiPoints * 0.95,
  };
  store.set({ bench: { phase: "done", result } });
  (window as unknown as { __DU_BENCH__: BenchResult }).__DU_BENCH__ = result;
  return result;
}
