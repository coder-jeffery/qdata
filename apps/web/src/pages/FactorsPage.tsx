import { useState } from "react";
import { api } from "../api/client";
import { Pagination } from "../shared/Pagination";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";
import { usePagination } from "../shared/usePagination";

export function FactorsPage() {
  const [date, setDate] = useState<string>("");
  const { data, err, loading } = useAsync(
    () => api.factorCoverage(date || undefined),
    [date],
  );
  const items = data?.items || [];
  const pag = usePagination(items, 20, date || data?.trade_date || "");

  if (loading && !data) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;
  if (!data) return null;

  const dates = data.dates || [];
  const active = date || data.trade_date || "";

  return (
    <div className="content">
      {data.error && <p className="err">{data.error}</p>}
      <div className="panel" style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>因子覆盖</h3>
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
        {loading && <span className="muted">刷新中…</span>}
      </div>

      <div className="panel">
        <table className="data">
          <thead>
            <tr>
              <th>因子</th>
              <th>有效数</th>
              <th>宇宙</th>
              <th>覆盖率</th>
              <th>P50</th>
              <th>均值</th>
            </tr>
          </thead>
          <tbody>
            {pag.view.map((r) => {
              const cov = Number(r.coverage);
              const low = !Number.isNaN(cov) && cov < 0.9;
              return (
                <tr key={String(r.factor)}>
                  <td className="mono">{r.factor}</td>
                  <td className="mono">{fmtNum(r.n_valid)}</td>
                  <td className="mono">{fmtNum(r.universe)}</td>
                  <td className={`mono ${low ? "down" : "up"}`}>
                    {Number.isNaN(cov) ? "—" : `${(cov * 100).toFixed(1)}%`}
                  </td>
                  <td className="mono">
                    {r.p50 != null ? Number(r.p50).toFixed(4) : "—"}
                  </td>
                  <td className="mono">
                    {r.mean != null ? Number(r.mean).toFixed(4) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Pagination
          page={pag.page}
          pageSize={pag.pageSize}
          total={pag.total}
          onChange={pag.setPage}
        />
        {!data.items?.length && <p className="muted">暂无因子覆盖数据</p>}
      </div>
    </div>
  );
}
