import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";

export function BacktestDetailPage() {
  const { runId = "" } = useParams();
  const { data, err, loading } = useAsync(() => api.backtest(runId), [runId]);

  if (loading) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;
  if (!data) return null;

  const m = data.metrics || {};
  const meta = data.meta || {};

  return (
    <div className="content">
      <div className="btn-row" style={{ marginBottom: 14 }}>
        <Link className="btn ghost" to="/research">
          返回研究
        </Link>
        <span className="mono muted">{data.run_id}</span>
      </div>

      <div className="cards">
        <div className="card">
          <div className="k">夏普</div>
          <div className={`v ${Number(m.sharpe) >= 0 ? "up" : "down"}`}>
            {m.sharpe != null ? Number(m.sharpe).toFixed(2) : "—"}
          </div>
          <div className="s">{String(meta.factor || "—")}</div>
        </div>
        <div className="card">
          <div className="k">年化</div>
          <div className="v mono">
            {m.ann_return != null ? `${(Number(m.ann_return) * 100).toFixed(1)}%` : "—"}
          </div>
          <div className="s">{String(meta.universe || "—")}</div>
        </div>
        <div className="card">
          <div className="k">最大回撤</div>
          <div className="v mono down">
            {m.max_drawdown != null ? `${(Number(m.max_drawdown) * 100).toFixed(1)}%` : "—"}
          </div>
          <div className="s">{String(meta.execution || "—")}</div>
        </div>
        <div className="card">
          <div className="k">换手</div>
          <div className="v mono">
            {m.turnover != null ? Number(m.turnover).toFixed(2) : "—"}
          </div>
          <div className="s">成交 {fmtNum(m.n_fills)}</div>
        </div>
      </div>

      <div className="panel">
        <h3>净值尾部（最多 120 点）</h3>
        <table className="data">
          <thead>
            <tr>
              <th>日期</th>
              <th>净值</th>
              <th>基准</th>
            </tr>
          </thead>
          <tbody>
            {(data.equity || []).slice(-40).map((r, i) => (
              <tr key={i}>
                <td className="mono">{String(r.trade_date ?? r.date ?? "—")}</td>
                <td className="mono">
                  {r.nav != null || r.equity != null
                    ? Number(r.nav ?? r.equity).toFixed(4)
                    : "—"}
                </td>
                <td className="mono">
                  {r.benchmark_nav != null ? Number(r.benchmark_nav).toFixed(4) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data.equity?.length && <p className="muted">无净值序列</p>}
      </div>

      <div className="panel">
        <h3>成交样本</h3>
        <table className="data">
          <thead>
            <tr>
              <th>日期</th>
              <th>代码</th>
              <th>方向</th>
              <th>数量</th>
              <th>价格</th>
            </tr>
          </thead>
          <tbody>
            {(data.fills || []).slice(0, 30).map((r, i) => (
              <tr key={i}>
                <td className="mono">{String(r.trade_date ?? "—")}</td>
                <td className="mono">{String(r.exchange_code ?? r.ts_code ?? "—")}</td>
                <td>{String(r.side ?? "—")}</td>
                <td className="mono">{fmtNum(r.qty ?? r.quantity)}</td>
                <td className="mono">{fmtNum(r.price, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
