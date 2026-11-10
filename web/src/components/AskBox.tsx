import { useEffect, useState } from "react";
import { fmtUtc } from "../clock";
import { engineRegistry } from "../globe/engine";
import type { AskResult } from "../protocol";
import { useStore } from "../store";

const PRESETS = [
  "过去一小时维基编辑最多的 5 个地区？",
  "过去 24 小时最强的地震在哪里？",
  "最近一小时有哪些异常告警？",
  "现在空中有多少架航班？",
];

type Status = { enabled: boolean; model: string | null } | null;

export function AskBox() {
  const mode = useStore((s) => s.mode);
  const qa = useStore((s) => s.replay?.qa);
  const [status, setStatus] = useState<Status>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResult | null>(null);
  const [err, setErr] = useState("");
  const [showSql, setShowSql] = useState(false);
  const [open, setOpen] = useState(true);
  const replay = mode === "replay";

  useEffect(() => {
    if (replay) return;
    fetch("/api/ask/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, model: null }));
  }, [replay]);

  const show = (r: AskResult) => {
    setRes(r);
    setErr("");
    setShowSql(false);
    engineRegistry.get()?.setHighlights(r.highlights ?? []);
  };

  const ask = async (question: string) => {
    question = question.trim();
    if (question.length < 2 || busy) return;
    setQ(question);
    setBusy(true);
    setErr("");
    try {
      const r = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const body = await r.json();
      if (!r.ok) setErr(body.error ?? (r.status === 422 ? "问题长度需在 2~300 字之间" : `请求失败 HTTP ${r.status}`));
      else show({ ...body, question });
    } catch (e) {
      setErr(`网络错误：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const clear = () => {
    setRes(null);
    setErr("");
    engineRegistry.get()?.setHighlights([]);
  };

  const enabled = !replay && status?.enabled;
  const chips = replay ? (qa ?? []).map((r) => r.question ?? "") : PRESETS;

  if (!open) {
    return (
      <button className="ask-fab" onClick={() => setOpen(true)}>
        ✦ 问问数据
      </button>
    );
  }

  return (
    <div className="ask">
      {res && (
        <div className="ask-answer">
          <div className="ask-q">
            {res.question}
            <button className="x" onClick={clear} title="清除">
              ×
            </button>
          </div>
          <p>{res.answer}</p>
          {res.highlights.length > 0 && (
            <div className="ask-hl">
              {res.highlights.map((h) => (
                <span key={`${h.lat},${h.lng}`} onClick={() => engineRegistry.get()?.flyTo(h.lat, h.lng, 1.6)}>
                  {h.label}
                  {h.geo_precision === "approx" ? " ≈" : ""}
                </span>
              ))}
            </div>
          )}
          <div className="ask-meta">
            {res.model} · {res.sql.length} 条 SQL · {(res.elapsed_ms / 1000).toFixed(1)}s
            {replay && res.asked_ms ? ` · 录制于 ${fmtUtc(res.asked_ms, true)}` : ""}
            {res.sql.length > 0 && (
              <button className="link" onClick={() => setShowSql(!showSql)}>
                {showSql ? "收起 SQL" : "查看 SQL"}
              </button>
            )}
          </div>
          {showSql && (
            <div className="ask-sql">
              {res.sql.map((s, i) => (
                <pre key={i}>{s}</pre>
              ))}
              {res.table && (
                <table>
                  <thead>
                    <tr>
                      {res.table.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {res.table.rows.slice(0, 8).map((r, i) => (
                      <tr key={i}>
                        {r.map((v, j) => (
                          <td key={j}>{String(v ?? "")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}
      {err && <div className="ask-err">{err}</div>}
      <div className="ask-chips">
        {chips.map((c, i) => (
          <button
            key={c || i}
            disabled={busy || (!replay && !enabled)}
            onClick={() => (replay ? qa && show(qa[i]) : ask(c))}
          >
            {c}
          </button>
        ))}
        {replay && chips.length === 0 && <span className="muted">这段回放没有录制问答</span>}
      </div>
      <form
        className="ask-input"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(q);
        }}
      >
        <span className="spark">✦</span>
        <input
          value={q}
          maxLength={300}
          disabled={!enabled || busy}
          onChange={(e) => setQ(e.target.value)}
          placeholder={
            replay
              ? "回放模式只能查看上面的预置问答；本地运行完整版可自由提问"
              : status === null
                ? "连接中…"
                : enabled
                  ? `用中文问问这个世界正在发生什么（${status.model}）`
                  : "AI 提问未开启：在 .env 设置 LLM_API_KEY 后重启 gateway"
          }
        />
        <button type="submit" disabled={!enabled || busy || q.trim().length < 2}>
          {busy ? "思考中…" : "提问"}
        </button>
        <button type="button" className="x" onClick={() => setOpen(false)} title="收起">
          –
        </button>
      </form>
    </div>
  );
}
