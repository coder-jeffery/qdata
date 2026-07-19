import { api } from "../api/client";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";

export function FinancePage() {
  const { data, err, loading } = useAsync(() => api.dataFinance(), []);

  if (loading) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;
  if (!data) return null;

  const s = data.summary || {};
  const lag = data.lag || {};

  return (
    <div className="content">
      {data.error && <p className="err">{data.error}</p>}
      <div className="cards">
        <div className="card">
          <div className="k">公告水位</div>
          <div className="v mono">{String(s.max_ann || "—")}</div>
          <div className="s">相对日线滞后 {String(lag.lag_days ?? "—")} 天</div>
        </div>
        <div className="card">
          <div className="k">证券数</div>
          <div className="v mono">{fmtNum(s.securities)}</div>
          <div className="s">{fmtNum(s.rows)} 行财报</div>
        </div>
        <div className="card">
          <div className="k">三表行数</div>
          <div className="v" style={{ fontSize: 16 }}>
            {fmtNum(s.n_income)} / {fmtNum(s.n_balance)} / {fmtNum(s.n_cashflow)}
          </div>
          <div className="s">利润 / 资产负债 / 现金流</div>
        </div>
        <div className="card">
          <div className="k">异常</div>
          <div className={`v mono ${Number(s.bad_ann_lt_report) > 0 ? "down" : "up"}`}>
            {fmtNum(s.bad_ann_lt_report)}
          </div>
          <div className="s">ann_date &lt; report_date</div>
        </div>
      </div>

      <div className="panel">
        <h3>PIT 科目覆盖（抽样）</h3>
        <table className="data">
          <thead>
            <tr>
              <th>科目</th>
              <th>命中</th>
              <th>样本</th>
              <th>覆盖率</th>
            </tr>
          </thead>
          <tbody>
            {(data.pit || []).map((r) => (
              <tr key={String(r.field)}>
                <td className="mono">{String(r.field)}</td>
                <td className="mono">{fmtNum(r.n_hit)}</td>
                <td className="mono">{fmtNum(r.sample)}</td>
                <td className="mono">
                  {r.coverage != null ? `${(Number(r.coverage) * 100).toFixed(1)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data.pit?.length && <p className="muted">暂无 PIT 覆盖（需日线 asof）</p>}
      </div>

      <div className="panel">
        <h3>公告月度</h3>
        <table className="data">
          <thead>
            <tr>
              <th>月</th>
              <th>行数</th>
              <th>证券数</th>
            </tr>
          </thead>
          <tbody>
            {(data.monthly || [])
              .slice()
              .reverse()
              .map((r, i) => (
                <tr key={i}>
                  <td className="mono">{String(r.month ?? "—")}</td>
                  <td className="mono">{fmtNum(r.rows)}</td>
                  <td className="mono">{fmtNum(r.securities)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
