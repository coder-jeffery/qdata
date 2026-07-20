import { api } from "../api/client";
import { Pagination } from "../shared/Pagination";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";
import { usePagination } from "../shared/usePagination";

export function HealthPage() {
  const { data, err, loading } = useAsync(() => api.dataHealth(), []);
  const marks = data?.summary?.watermarks || [];
  const lag = data?.lag || [];
  const marksPag = usePagination(marks, 20);
  const lagPag = usePagination(lag, 20);

  if (loading) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;
  if (!data) return null;

  const s = data.summary;

  return (
    <div className="content">
      {data.error && <p className="err">{data.error}</p>}
      <div className="cards">
        <div className="card">
          <div className="k">最新发布</div>
          <div className="v mono">{s.latest_published || "—"}</div>
          <div className="s">dataset_version</div>
        </div>
        <div className="card">
          <div className="k">日线水位</div>
          <div className="v mono">{s.daily_bar_max || "—"}</div>
          <div className="s">
            {fmtNum(s.daily_bar_days)} 日 · {fmtNum(s.daily_bar_rows)} 行
          </div>
        </div>
        <div className="card">
          <div className="k">证券主档</div>
          <div className="v mono">{fmtNum(s.security_master)}</div>
          <div className="s">security_master</div>
        </div>
        <div className="card">
          <div className="k">Extras 滞后</div>
          <div className={`v mono ${Number(s.extras_stale) > 0 ? "down" : "up"}`}>
            {s.extras_stale ?? 0}
          </div>
          <div className="s">
            漂移{" "}
            {s.last_drift_pct != null ? `${(Number(s.last_drift_pct) * 100).toFixed(2)}%` : "—"}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>表水位</h3>
        <table className="data">
          <thead>
            <tr>
              <th>表</th>
              <th>起</th>
              <th>止</th>
              <th>行数</th>
              <th>天数</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {marksPag.view.map((m) => (
              <tr key={m.name}>
                <td className="mono">{m.name}</td>
                <td className="mono">{m.min_date || "—"}</td>
                <td className="mono">{m.max_date || "—"}</td>
                <td className="mono">{fmtNum(m.rows)}</td>
                <td className="mono">{fmtNum(m.days)}</td>
                <td className={m.ok ? "up" : "down"}>{m.note || (m.ok ? "ok" : "fail")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={marksPag.page}
          pageSize={marksPag.pageSize}
          total={marksPag.total}
          onChange={marksPag.setPage}
        />
      </div>

      <div className="panel">
        <h3>相对日线滞后</h3>
        <table className="data">
          <thead>
            <tr>
              <th>表</th>
              <th>最大日</th>
              <th>滞后天</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {lagPag.view.map((r) => (
              <tr key={r.table}>
                <td className="mono">{r.table}</td>
                <td className="mono">{r.max_date || "—"}</td>
                <td className="mono">{r.lag_days ?? "—"}</td>
                <td className={r.status === "stale" ? "down" : ""}>{r.status || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={lagPag.page}
          pageSize={lagPag.pageSize}
          total={lagPag.total}
          onChange={lagPag.setPage}
        />
      </div>
    </div>
  );
}
