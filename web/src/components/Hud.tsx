import { useStore } from "../store";

const CONN: Record<string, string> = { open: "已连接", connecting: "连接中", closed: "已断开" };

export function Hud() {
  const fps = useStore((s) => s.fps);
  const counts = useStore((s) => s.counts);
  const conn = useStore((s) => s.conn);
  const retry = useStore((s) => s.retryInMs);
  const net = useStore((s) => s.net);
  const cap = useStore((s) => s.cap);
  const dropped = useStore((s) => s.dropped);
  const warnings = useStore((s) => s.warnings);
  const total = counts.wiki + counts.usgs + counts.opensky;
  return (
    <div className="hud">
      <span className={fps.fps >= 55 ? "good" : fps.fps >= 40 ? "mid" : "bad"}>{fps.fps.toFixed(0)} FPS</span>
      <span>1% Low {fps.low1.toFixed(0)}</span>
      <span>{total.toLocaleString()} 点</span>
      <span>{(net.bytesPerSec / 1024).toFixed(1)} KB/s</span>
      <span className={`conn ${conn}`}>
        {CONN[conn]}
        {conn === "closed" && retry ? `，${Math.ceil(retry / 1000)} 秒后重连` : ""}
      </span>
      {cap > 0 && <span className="muted">推送上限 {cap}/包 · 已抽样丢弃 {dropped.wiki.toLocaleString()}</span>}
      {warnings.map((w) => (
        <span key={w} className="warn">⚠ {w}</span>
      ))}
    </div>
  );
}
