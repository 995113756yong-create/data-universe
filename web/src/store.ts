import { useSyncExternalStore } from "react";
import type { AlertItem, AskResult, Layer, MetricsMsg } from "./protocol";
import type { FpsStats } from "./hud/fps";
import type { QuakeItem } from "./stream/decode";

export interface BenchResult extends FpsStats {
  wiki_points: number;
  flights: number;
  dpr: number;
  viewport: string;
  user_agent: string;
  pass: boolean;
}

export interface ReplayUi {
  id: string;
  title: string;
  startMs: number;
  endMs: number;
  vMs: number;
  speed: number;
  playing: boolean;
  buffering: boolean;
  qa: AskResult[];
  alertMarks: number[]; // 告警时间点（进度条刻度）
  sampling: { wiki_per_min: number; flight_permille: number; flight_step_s: number };
}

export interface UiState {
  conn: "connecting" | "open" | "closed";
  retryInMs?: number;
  metrics?: MetricsMsg;
  quakes: QuakeItem[];
  net: { bytesPerSec: number; msgsPerSec: number; lagP50: number; lagP95: number; lagN: number };
  fps: FpsStats;
  counts: { wiki: number; usgs: number; opensky: number };
  dropped: { wiki: number };
  cap: number;
  layers: Record<Layer, boolean>;
  warnings: string[];
  mode: "live" | "replay";
  alerts: AlertItem[];
  toasts: AlertItem[];
  replay?: ReplayUi;
  bench?: { phase: "warmup" | "recording" | "done"; result?: BenchResult };
}

let state: UiState = {
  conn: "connecting",
  quakes: [],
  net: { bytesPerSec: 0, msgsPerSec: 0, lagP50: NaN, lagP95: NaN, lagN: 0 },
  fps: { fps: 0, low1: 0, frames: 0, durationS: 0 },
  counts: { wiki: 0, usgs: 0, opensky: 0 },
  dropped: { wiki: 0 },
  cap: 0,
  layers: { wiki: true, usgs: true, opensky: true },
  warnings: [],
  mode: "live",
  alerts: [],
  toasts: [],
};
const listeners = new Set<() => void>();

export const store = {
  get: () => state,
  set(patch: Partial<UiState>) {
    state = { ...state, ...patch };
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  warn(msg: string) {
    if (!state.warnings.includes(msg)) store.set({ warnings: [...state.warnings, msg] });
  },
};

/** selector 必须返回 state 里已有的引用或原始值，不要在 selector 里新建对象 */
export function useStore<T>(sel: (s: UiState) => T): T {
  return useSyncExternalStore(store.subscribe, () => sel(state));
}
