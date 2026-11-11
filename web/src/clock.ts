// 全局时钟。实时模式 = 墙上时间；回放模式 = 回放器的虚拟时间。
// 渲染引擎、航位推算、面板里的「几分钟前」都从这里取时间，回放的倍速 / 暂停 / 拖动因此对所有图层生效。
let source: () => number = () => Date.now();

export const clock = {
  now: (): number => source(),
  use(fn: () => number) {
    source = fn;
  },
  reset() {
    source = () => Date.now();
  },
};

export function ago(ms: number, now = clock.now()): string {
  const s = Math.max(0, (now - ms) / 1000);
  if (s < 60) return `${Math.round(s)} 秒前`;
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`;
  return `${Math.round(s / 3600)} 小时前`;
}

export function fmtUtc(ms: number, withDate = false): string {
  const iso = new Date(ms).toISOString();
  return (withDate ? iso.slice(0, 10) + " " : "") + iso.slice(11, 19) + " UTC";
}
