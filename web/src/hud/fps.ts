export interface FpsStats { fps: number; low1: number; frames: number; durationS: number }

/** 平均帧率 = 帧数 / 总时长；1% Low = 最慢 1% 帧耗时对应的帧率 */
export function computeStats(frameMs: number[]): FpsStats {
  const n = frameMs.length;
  if (n === 0) return { fps: 0, low1: 0, frames: 0, durationS: 0 };
  const total = frameMs.reduce((a, b) => a + b, 0);
  const sorted = [...frameMs].sort((a, b) => a - b);
  const p99 = sorted[Math.min(n - 1, Math.floor(n * 0.99))];
  return {
    fps: Math.round((n / (total / 1000)) * 10) / 10,
    low1: Math.round((1000 / p99) * 10) / 10,
    frames: n,
    durationS: Math.round(total) / 1000,
  };
}

/** requestAnimationFrame 帧率计。window.__DU_STATS__ 供压测脚本读取 */
export class FpsMeter {
  private last = 0;
  private window: number[] = [];
  private recording: number[] | null = null;
  current: FpsStats = { fps: 0, low1: 0, frames: 0, durationS: 0 };

  frame(now: number) {
    if (this.last) {
      const dt = now - this.last;
      if (dt < 1000) {
        this.window.push(dt);
        this.recording?.push(dt);
      }
    }
    this.last = now;
    const total = this.window.reduce((a, b) => a + b, 0);
    if (total >= 1000) {
      this.current = computeStats(this.window);
      this.window = [];
      (window as unknown as { __DU_STATS__: FpsStats }).__DU_STATS__ = this.current;
    }
  }

  startRecording() {
    this.recording = [];
  }

  stopRecording(): FpsStats {
    const s = computeStats(this.recording ?? []);
    this.recording = null;
    return s;
  }
}
