import { engineRegistry } from "../globe/engine";
import type { Layer } from "../protocol";
import { useStore } from "../store";
import { TrendChart } from "./TrendChart";

const fmt = (n: number | undefined, d = 0) =>
  n === undefined || Number.isNaN(n) ? "—" : n.toLocaleString("zh-CN", { maximumFractionDigits: d });

const SOURCE_NAME: Record<Layer, string> = { wiki: "维基百科", usgs: "USGS 地震", opensky: "OpenSky 航班" };

function ago(ms: number) {
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return `${Math.round(s)} 秒前`;
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`;
  return `${Math.round(s / 3600)} 小时前`;
}

export function MetricsPanel() {
  const m = useStore((s) => s.metrics);
  const net = useStore((s) => s.net);
  const quakes = useStore((s) => s.quakes);

  return (
    <aside className="panel">
      <div className="cards">
        <div className="card wiki">
          <div className="label">维基编辑 / 秒</div>
          <div className="value">{fmt(m?.eps.wiki, 1)}</div>
          <div className="sub">近 1 分钟 {fmt(m?.last_minute.wiki)} 条</div>
        </div>
        <div className="card flight">
          <div className="label">在空航班</div>
          <div className="value">{fmt(m?.flights_tracked)}</div>
          <div className="sub">{m?.sources.opensky.recv_ms ? `上次更新 ${ago(m.sources.opensky.recv_ms)}` : "等待数据"}</div>
        </div>
        <div className="card quake">
          <div className="label">24 小时地震</div>
          <div className="value">{fmt(m?.quakes_24h?.count)}</div>
          <div className="sub">最大 M{fmt(m?.quakes_24h?.max_mag, 1)}</div>
        </div>
        <div className="card lag">
          <div className="label">链路延迟 P95</div>
          <div className="value">{fmt(net.lagP95)}<small> ms</small></div>
          <div className="sub">采集 → 浏览器（维基）</div>
        </div>
      </div>

      <section>
        <h3>近 30 分钟</h3>
        <TrendChart trend={m?.trend} />
      </section>

      <section>
        <h3>数据源</h3>
        <ul className="sources">
          {(["wiki", "usgs", "opensky"] as Layer[]).map((l) => {
            const st = m?.sources[l];
            return (
              <li key={l}>
                <span className={`dot ${st?.status ?? "waiting"}`} />
                {SOURCE_NAME[l]}
                <span className="muted">{st?.recv_ms ? ago(st.recv_ms) : "等待数据"}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h3>热点地区（近 10 分钟）</h3>
        <ol className="regions">
          {(m?.top_regions ?? []).slice(0, 6).map((r) => (
            <li key={`${r.source}-${r.region}`}>
              <span className={`tag ${r.source}`}>{r.source === "wiki" ? "编辑" : "地震"}</span>
              {r.region}
              <span className="muted">{fmt(r.cnt)}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="grow">
        <h3>最新地震 <span className="muted">点击定位</span></h3>
        <ul className="quakes">
          {quakes.slice(0, 12).map((q) => (
            <li key={q.id} onClick={() => engineRegistry.get()?.flyTo(q.lat, q.lng)}>
              <span className={`mag ${q.mag >= 5 ? "big" : q.mag >= 3 ? "mid" : ""}`}>{q.mag.toFixed(1)}</span>
              <span className="qtitle">{q.title.replace(/^M -?[\d.?]+ - /, "")}</span>
              <span className="muted">{ago(q.eventMs)}</span>
            </li>
          ))}
        </ul>
      </section>

      <footer className="note">
        维基编辑没有真实坐标，按语言映射到国家并做随机散布（近似位置）。航班地区为飞机注册国。
      </footer>
    </aside>
  );
}
