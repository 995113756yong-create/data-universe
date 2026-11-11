import { alertText, SEVERITY_COLOR } from "../alerts";
import { ago } from "../clock";
import { engineRegistry } from "../globe/engine";
import { useStore } from "../store";

const SEV: Record<string, string> = { medium: "中", high: "高", critical: "严重" };

export function AlertFeed() {
  const alerts = useStore((s) => s.alerts);
  useStore((s) => s.metrics); // 每次指标刷新（约 2 秒）顺带刷新「几分钟前」
  return (
    <section className="alert-feed">
      <h3>
        异常告警 <span className="muted">{alerts.length ? "点击定位" : "暂无"}</span>
      </h3>
      <ul>
        {alerts.slice(0, 8).map((a) => (
          <li
            key={a.alert_id}
            className={a.lat === null ? "nogeo" : ""}
            onClick={() => a.lat !== null && a.lng !== null && engineRegistry.get()?.flyTo(a.lat, a.lng, 1.6)}
            title={a.geo_precision === "approx" ? "维基告警的位置是该地区中心点（近似）" : undefined}
          >
            <span className="sev" style={{ background: SEVERITY_COLOR[a.severity] }}>
              {SEV[a.severity]}
            </span>
            <span className="atext">{alertText(a)}</span>
            <span className="muted">{ago(a.event_time_ms)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AlertToasts() {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="toasts">
      {toasts.map((a) => (
        <div
          key={a.alert_id}
          className={`toast ${a.severity}`}
          onClick={() => a.lat !== null && a.lng !== null && engineRegistry.get()?.flyTo(a.lat, a.lng, 1.6)}
        >
          <b>{a.alert_type === "wiki_spike" ? "编辑激增" : "显著地震"}</b>
          {alertText(a)}
        </div>
      ))}
    </div>
  );
}
