// 回放播放器：按虚拟时钟把切片里的事件喂给渲染引擎，复用实时模式的解码函数和渲染路径
import { clock } from "../clock";
import type { UniverseEngine } from "../globe/engine";
import { P, type FlightRow, type PointRow } from "../protocol";
import { store } from "../store";
import { decodeFlights, decodePoints, decodeQuakes } from "../stream/decode";
import { pushAlerts, pushQuakes } from "../stream/sink";
import { fetchJson, MANIFEST_VERSION, type Chunk, type Manifest, type ReplayIndex } from "./format";
import { alertShowTime, chunkIndex, flightTime, metricsAt, pointTime, ReplayClock, timeRange } from "./timeline";

const TICK_MS = 100;
const PREFETCH = 3; // 预取后面几个切片
const KEEP_BEHIND = 2;
const FLIGHT_PREROLL_MS = 10 * 60_000; // 拖动后补画最近 10 分钟的航班位置
const WIKI_PREROLL_MS = 60_000;
export const SPEEDS = [1, 10, 60] as const;

export class ReplayPlayer {
  private m!: Manifest;
  private clk!: ReplayClock;
  private base = "";
  private readonly chunks = new Map<number, Chunk>();
  private readonly loading = new Map<number, Promise<void>>();
  private lastEmit = 0;
  private timer = 0;
  private metricsTimer = 0;
  private buffering = false;
  private resumeAfterBuffer = false;
  private seeking = 0; // seek 令牌：连续拖动时只有最后一次生效
  private inSeek = false;

  constructor(private readonly engine: UniverseEngine, private readonly root: string) {}

  async start(id?: string | null): Promise<void> {
    const idx = await fetchJson<ReplayIndex>(`${this.root}index.json`);
    const entry = (id && idx.replays.find((r) => r.id === id)) || idx.replays[0];
    if (!entry) throw new Error("没有可用的回放（先执行 make replay-export）");
    this.base = `${this.root}${entry.id}/`;
    this.m = await fetchJson<Manifest>(`${this.base}manifest.json`);
    if (this.m.v !== MANIFEST_VERSION) throw new Error(`回放包版本 ${this.m.v} 不受支持`);
    this.clk = new ReplayClock(this.m.start_ms, this.m.end_ms);
    clock.use(() => this.clk.now());
    // 着色器时间基准放在回放开始前 24 小时（地震快照最早到这里），float32 精度足够
    this.engine.setTimeBase(this.m.start_ms - 24 * 3600_000);
    store.set({
      mode: "replay",
      conn: "open",
      replay: {
        id: this.m.id,
        title: this.m.title,
        startMs: this.m.start_ms,
        endMs: this.m.end_ms,
        vMs: this.m.start_ms,
        speed: 1,
        playing: false,
        buffering: false,
        qa: this.m.qa ?? [],
        alertMarks: this.m.alerts.map(alertShowTime).filter((t) => t >= this.m.start_ms && t <= this.m.end_ms),
        sampling: this.m.sampling,
      },
    });
    await this.seek(this.m.start_ms);
    this.timer = window.setInterval(this.tick, TICK_MS);
    this.metricsTimer = window.setInterval(this.pushMetrics, 1000);
    this.pushMetrics();
    this.play();
  }

  stop() {
    window.clearInterval(this.timer);
    window.clearInterval(this.metricsTimer);
    clock.reset();
  }

  play() {
    this.clk.play();
    this.sync();
  }

  pause() {
    this.resumeAfterBuffer = false;
    this.clk.pause();
    this.sync();
  }

  setSpeed(s: number) {
    this.clk.setSpeed(s);
    this.sync();
  }

  /** 拖动进度：清空图层，补画目标时刻之前的航班 / 维基 / 地震 / 告警 */
  async seek(v: number): Promise<void> {
    const token = ++this.seeking;
    this.inSeek = true;
    const wasPlaying = this.clk.playing || this.resumeAfterBuffer;
    this.resumeAfterBuffer = false;
    this.buffering = false;
    this.clk.pause();
    this.clk.seek(v);
    v = this.clk.now();
    const from = Math.max(this.m.start_ms, v - FLIGHT_PREROLL_MS);
    const need: Promise<void>[] = [];
    for (let i = chunkIndex(this.m, from); i <= chunkIndex(this.m, v); i++) need.push(this.load(i));
    this.sync();
    await Promise.all(need);
    if (token !== this.seeking) return; // 期间又拖动了一次
    this.engine.reset();
    store.set({ quakes: [], alerts: [], toasts: [] });
    this.emitFlights(from - 1, v); // 第 0 片里有开始前 10 分钟的预热位置，from-1 包含它们
    if (from <= this.m.start_ms) this.emitFlights(-Infinity, from - 1);
    this.emitWiki(v - WIKI_PREROLL_MS, v);
    pushQuakes(this.engine, decodeQuakes(this.m.quakes.filter((q) => q[P.eventMs] <= v && q[P.eventMs] > v - 24 * 3600_000)));
    pushAlerts(this.engine, this.m.alerts.filter((a) => alertShowTime(a) <= v && alertShowTime(a) > v - 6 * 3600_000), false);
    this.lastEmit = v;
    this.inSeek = false;
    if (wasPlaying) this.clk.play();
    this.pushMetrics();
    this.sync();
  }

  private load(i: number): Promise<void> {
    if (i < 0 || i >= this.m.chunks.length || this.chunks.has(i)) return Promise.resolve();
    let p = this.loading.get(i);
    if (!p) {
      p = fetchJson<Chunk>(`${this.base}${this.m.chunks[i].file}`)
        .then((c) => {
          this.chunks.set(i, c);
        })
        .catch((e) => {
          store.warn(`回放切片 ${i} 加载失败：${(e as Error).message}`);
          this.chunks.set(i, { t0: this.m.chunks[i].t0, wiki: [], opensky: [] }); // 用空切片顶上，不卡住播放
        })
        .finally(() => this.loading.delete(i));
      this.loading.set(i, p);
    }
    return p;
  }

  private tick = () => {
    if (this.inSeek) return;
    const v = this.clk.now();
    const cur = chunkIndex(this.m, v);
    for (let i = cur; i <= cur + PREFETCH; i++) void this.load(i);
    for (const k of this.chunks.keys()) if (k < chunkIndex(this.m, this.lastEmit) - KEEP_BEHIND) this.chunks.delete(k);

    // 需要的切片还没到：冻结虚拟时钟，等加载完再继续
    const missing = !this.chunks.has(cur) || !this.chunks.has(chunkIndex(this.m, this.lastEmit));
    if (missing) {
      if (this.clk.playing) {
        this.clk.pause();
        this.resumeAfterBuffer = true;
        this.buffering = true;
        this.sync();
      }
      return;
    }
    if (this.buffering) {
      this.buffering = false;
      if (this.resumeAfterBuffer) this.clk.play();
      this.resumeAfterBuffer = false;
    }
    if (v > this.lastEmit) {
      this.emitWiki(this.lastEmit, v);
      this.emitFlights(this.lastEmit, v);
      const qs = this.m.quakes.filter((q) => q[P.eventMs] > this.lastEmit && q[P.eventMs] <= v);
      if (qs.length) pushQuakes(this.engine, decodeQuakes(qs));
      const as = this.m.alerts.filter((a) => alertShowTime(a) > this.lastEmit && alertShowTime(a) <= v);
      if (as.length) pushAlerts(this.engine, as, true);
      this.lastEmit = v;
    }
    if (this.clk.ended && this.clk.playing) this.clk.pause();
    this.sync();
  };

  private emitWiki(from: number, to: number) {
    const rows: PointRow[] = [];
    for (let i = chunkIndex(this.m, from); i <= chunkIndex(this.m, to); i++) {
      const c = this.chunks.get(i);
      if (!c) continue;
      const [lo, hi] = timeRange(c.wiki, pointTime, from, to);
      for (let k = lo; k < hi; k++) rows.push(c.wiki[k]);
    }
    if (rows.length) this.engine.addWiki(decodePoints(rows, to));
  }

  private emitFlights(from: number, to: number) {
    const rows: FlightRow[] = [];
    const lo0 = Number.isFinite(from) ? chunkIndex(this.m, from) : 0;
    for (let i = lo0; i <= chunkIndex(this.m, to); i++) {
      const c = this.chunks.get(i);
      if (!c) continue;
      const [lo, hi] = timeRange(c.opensky, flightTime, from, to);
      for (let k = lo; k < hi; k++) rows.push(c.opensky[k]);
    }
    if (rows.length) this.engine.upsertFlights(decodeFlights(rows));
  }

  private pushMetrics = () => {
    if (!this.m) return;
    store.set({ metrics: metricsAt(this.m, this.clk.now(), this.engine.flights.count) });
  };

  private sync() {
    const r = store.get().replay;
    if (!r) return;
    store.set({
      replay: { ...r, vMs: this.clk.now(), speed: this.clk.speed, playing: this.clk.playing || this.resumeAfterBuffer, buffering: this.buffering },
    });
  }
}

let current: ReplayPlayer | null = null;
export const playerRegistry = {
  get: () => current,
  set: (p: ReplayPlayer | null) => (current = p),
};
