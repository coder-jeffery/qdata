import { useState } from "react";
import { api } from "../api/client";
import { useAsync } from "../shared/useAsync";

export function MonitorPage() {
  const [date, setDate] = useState<string>("");
  const { data, err, loading } = useAsync(
    () => api.monitor(date || undefined),
    [date],
  );

  if (loading && !data) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;
  if (!data) return null;

  const report = data.report || {};
  const dates = data.dates || [];
  const active = date || String(report.date || dates[0] || "");
  const alerts = Number(report.n_alerts || 0);

  return (
    <div className="content">
      <div className="panel" style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>因子监控</h3>
        <select
          className="btn ghost"
          style={{ minHeight: 34 }}
          value={active}
          onChange={(e) => setDate(e.target.value)}
        >
          {dates.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>

      {!report.date ? (
        <p className="muted">暂无监控报告。请先运行 monitor_factors 或 daily_run --post-m2。</p>
      ) : (
        <>
          <div className="cards">
            <div className="card">
              <div className="k">告警数</div>
              <div className={`v mono ${alerts > 0 ? "down" : "up"}`}>{alerts}</div>
            </div>
            <div className="card">
              <div className="k">宇宙规模</div>
              <div className="v mono">{String(report.universe_size ?? "—")}</div>
            </div>
            <div className="card">
              <div className="k">覆盖阈值</div>
              <div className="v mono">
                {report.min_coverage != null
                  ? `${(Number(report.min_coverage) * 100).toFixed(0)}%`
                  : "—"}
              </div>
            </div>
            <div className="card">
              <div className="k">来源</div>
              <div className="v" style={{ fontSize: 16 }}>
                {report.via === "daily_run" ? "日批" : String(report.via ?? "—")}
              </div>
            </div>
          </div>

          <div className="panel">
            <h3>覆盖明细</h3>
            <table className="data">
              <thead>
                <tr>
                  <th>因子</th>
                  <th>覆盖率</th>
                  <th>有效</th>
                  <th>宇宙</th>
                </tr>
              </thead>
              <tbody>
                {(data.coverage || []).map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{String(r.factor_name ?? r.factor ?? "—")}</td>
                    <td className="mono">
                      {r.coverage != null
                        ? `${(Number(r.coverage) * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="mono">{String(r.n_valid ?? "—")}</td>
                    <td className="mono">{String(r.universe_size ?? r.universe ?? "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
