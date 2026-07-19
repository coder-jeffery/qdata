import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type QuoteRow } from "../api/client";
import { useAsync } from "../shared/useAsync";
import { fmtNum } from "../shared/format";
import { pollJob } from "../shared/useJobPoll";
import { useToast } from "../shared/Toast";

export function JudgmentPage() {
  const toast = useToast();
  const { code: routeCode = "" } = useParams();
  const [input, setInput] = useState(routeCode || "600519.SH");
  const [code, setCode] = useState(routeCode || "600519.SH");
  const { data, err, loading } = useAsync(() => api.judgment(code), [code]);
  const [quote, setQuote] = useState<QuoteRow | null>(null);
  const [rtBusy, setRtBusy] = useState(false);

  useEffect(() => {
    if (routeCode) {
      setInput(routeCode);
      setCode(routeCode);
    }
  }, [routeCode]);

  useEffect(() => {
    let alive = true;
    api
      .realtimeQuotes([code])
      .then((d) => {
        if (!alive) return;
        setQuote(d.quotes?.[0] || null);
      })
      .catch(() => setQuote(null));
    return () => {
      alive = false;
    };
  }, [code]);

  async function refreshQuote() {
    setRtBusy(true);
    try {
      const r = await api.realtimeRefresh([code]);
      if (r.job_id) {
        const job = await pollJob(r.job_id, { timeoutMs: 45_000 });
        if (job.status === "failed") throw new Error(job.error || "刷新失败");
      }
      const d = await api.realtimeQuotes([code]);
      setQuote(d.quotes?.[0] || null);
      toast.ok(d.quotes?.length ? "已更新实时价" : "暂无实时快照");
    } catch (e) {
      toast.err((e as Error).message);
    } finally {
      setRtBusy(false);
    }
  }

  const card = data?.card;
  const price = quote?.price != null && quote.price !== "" ? Number(quote.price) : null;
  const pre =
    quote?.pre_close != null && quote.pre_close !== "" ? Number(quote.pre_close) : null;
  const chg = price != null && pre != null && pre !== 0 ? (price - pre) / pre : null;

  return (
    <div className="content">
      <div className="panel btn-row">
        <input
          className="mono"
          style={{
            height: 38,
            padding: "0 12px",
            borderRadius: 8,
            border: "1px solid var(--line-2)",
            background: "var(--panel)",
            minWidth: 160,
          }}
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          placeholder="600519.SH"
        />
        <button type="button" className="btn primary" onClick={() => setCode(input.trim())}>
          研判
        </button>
        <button type="button" className="btn ghost" disabled={rtBusy} onClick={refreshQuote}>
          {rtBusy ? "刷新中…" : "刷新实时价"}
        </button>
      </div>

      {loading && <p className="muted">载入中…</p>}
      {err && <p className="err">{err}</p>}

      {card && (
        <>
          <div className="cards">
            <div className="card">
              <div className="k">代码</div>
              <div className="v" style={{ fontSize: 20 }}>
                {String(card.code)}
              </div>
              <div className="s">asof {String(card.asof || "—")}</div>
            </div>
            <div className="card">
              <div className="k">立场</div>
              <div className="v" style={{ fontSize: 20 }}>
                {String(card.stance || "—")}
              </div>
              <div className="s">综合分 {card.composite != null ? Number(card.composite).toFixed(1) : "—"}</div>
            </div>
            <div className="card">
              <div className="k">相对强度</div>
              <div className={`v mono ${Number(card.relative_strength) >= 0 ? "up" : "down"}`}>
                {card.relative_strength != null
                  ? `${(Number(card.relative_strength) * 100).toFixed(1)}%`
                  : "—"}
              </div>
              <div className="s">窗口 {String(card.window ?? 20)} 日</div>
            </div>
            <div className="card">
              <div className="k">实时价</div>
              <div className={`v mono ${chg != null ? (chg >= 0 ? "up" : "down") : ""}`} style={{ fontSize: 20 }}>
                {price != null ? fmtNum(price, 2) : "—"}
              </div>
              <div className="s">
                {chg != null
                  ? `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}% · ${quote?.snapshot_ts || ""}`
                  : "Lake realtime · 无快照"}
              </div>
            </div>
          </div>

          <div className="panel">
            <h3>维度得分</h3>
            <table className="data">
              <thead>
                <tr>
                  <th>维度</th>
                  <th>得分</th>
                  <th>分位</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries((card.scores as Record<string, number | null>) || {}).map(
                  ([k, v]) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td className="mono">{v != null ? Number(v).toFixed(1) : "—"}</td>
                      <td className="mono">
                        {(card.percentiles as Record<string, number | null>)?.[k] != null
                          ? `${(
                              Number((card.percentiles as Record<string, number | null>)[k]) * 100
                            ).toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>
                  ),
                )}
              </tbody>
            </table>
          </div>

          <div className="panel">
            <h3>简报</h3>
            <pre
              className="mono"
              style={{
                whiteSpace: "pre-wrap",
                color: "var(--text-2)",
                lineHeight: 1.6,
                fontSize: 12,
              }}
            >
              {JSON.stringify(card.brief || card.tags || {}, null, 2)}
            </pre>
          </div>
        </>
      )}
    </div>
  );
}
