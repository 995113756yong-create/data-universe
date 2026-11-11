import { fmtUtc } from "../clock";
import { playerRegistry, SPEEDS } from "../replay/player";
import { useStore } from "../store";

export function ReplayBar() {
  const r = useStore((s) => s.replay);
  if (!r) return <div className="replay-bar">回放加载中…</div>;
  const p = playerRegistry.get();
  const span = r.endMs - r.startMs;
  const pct = (t: number) => `${(((t - r.startMs) / span) * 100).toFixed(2)}%`;
  return (
    <div className="replay-bar">
      <span className="badge">REPLAY</span>
      <button className="play" onClick={() => (r.playing ? p?.pause() : p?.play())} title={r.playing ? "暂停" : "播放"}>
        {r.playing ? "❚❚" : "▶"}
      </button>
      {SPEEDS.map((s) => (
        <button key={s} className={`speed ${r.speed === s ? "on" : ""}`} onClick={() => p?.setSpeed(s)}>
          {s}×
        </button>
      ))}
      <div className="track">
        {r.alertMarks.map((t, i) => (
          <i key={i} className="mark" style={{ left: pct(t) }} />
        ))}
        <input
          type="range"
          min={r.startMs}
          max={r.endMs}
          step={1000}
          value={Math.round(r.vMs)}
          onChange={(e) => void p?.seek(Number(e.target.value))}
        />
      </div>
      <span className="time">
        {fmtUtc(r.vMs)}
        {r.buffering ? " · 缓冲中" : ""}
      </span>
      <span className="muted" title={`维基每分钟最多 ${r.sampling.wiki_per_min} 条；航班抽样 ${r.sampling.flight_permille / 10}%`}>
        录制于 {r.title} · 已抽样
      </span>
    </div>
  );
}
