import { BENCH } from "../bench/synthetic";
import { useStore } from "../store";

export function BenchOverlay() {
  const bench = useStore((s) => s.bench);
  const fps = useStore((s) => s.fps);
  const r = bench?.result;
  return (
    <div className="bench">
      <h2>压测模式</h2>
      <p>
        {BENCH.wikiPoints.toLocaleString()} 维基点 + {BENCH.flights.toLocaleString()} 航班，地球自转，录制 {BENCH.durationS} 秒
      </p>
      {!r && (
        <p>
          {bench?.phase === "recording" ? "录制中…" : "预热中…"} 当前 {fps.fps.toFixed(0)} FPS
        </p>
      )}
      {r && (
        <table>
          <tbody>
            <tr><td>平均帧率</td><td>{r.fps} FPS（≥ {BENCH.passFps}）</td></tr>
            <tr><td>1% Low</td><td>{r.low1} FPS（≥ {BENCH.passLow1}）</td></tr>
            <tr><td>点数</td><td>{r.wiki_points.toLocaleString()} + {r.flights.toLocaleString()}</td></tr>
            <tr><td>视口 / DPR</td><td>{r.viewport} / {r.dpr}</td></tr>
            <tr><td>结论</td><td className={r.pass ? "good" : "bad"}>{r.pass ? "通过" : "未通过"}</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
