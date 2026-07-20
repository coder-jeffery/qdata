import { useState } from "react";
import { api } from "../api/client";
import { Pagination } from "../shared/Pagination";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";
import { usePagination } from "../shared/usePagination";

export function UniversePage() {
  const [index, setIndex] = useState("000905.SH");
  const { data, err, loading } = useAsync(() => api.universe(undefined, index), [index]);
  const sizes = data?.sizes || [];
  const industry = data?.industry || [];
  const sizesPag = usePagination(sizes, 20, index);
  const indPag = usePagination(industry, 20, index);

  if (loading && !data) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;
  if (!data) return null;

  const cov = data.coverage || {};

  return (
    <div className="content">
      {data.error && <p className="err">{data.error}</p>}
      <div className="panel" style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>选股域 / 行业 · {data.trade_date || "—"}</h3>
        <select
          className="btn ghost"
          style={{ minHeight: 34 }}
          value={index}
          onChange={(e) => setIndex(e.target.value)}
        >
          <option value="000300.SH">沪深300</option>
          <option value="000905.SH">中证500</option>
          <option value="000852.SH">中证1000</option>
          <option value="ALL">全市场</option>
        </select>
      </div>

      <div className="cards">
        <div className="card">
          <div className="k">行业覆盖率</div>
          <div className="v mono">
            {cov.coverage != null ? `${(Number(cov.coverage) * 100).toFixed(1)}%` : "—"}
          </div>
          <div className="s">
            映射 {fmtNum(cov.mapped)} / 宇宙 {fmtNum(cov.universe)}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>指数成分规模</h3>
        <table className="data">
          <thead>
            <tr>
              <th>指数</th>
              <th>成分数</th>
            </tr>
          </thead>
          <tbody>
            {sizesPag.view.map((r) => (
              <tr key={String(r.index_code)}>
                <td className="mono">{String(r.index_code)}</td>
                <td className="mono">{fmtNum(r.members)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={sizesPag.page}
          pageSize={sizesPag.pageSize}
          total={sizesPag.total}
          onChange={sizesPag.setPage}
        />
      </div>

      <div className="panel">
        <h3>行业分布（{index}）</h3>
        <table className="data">
          <thead>
            <tr>
              <th>行业</th>
              <th>家数</th>
              <th>占比</th>
            </tr>
          </thead>
          <tbody>
            {indPag.view.map((r, i) => (
              <tr key={i}>
                <td>{String(r.industry_name ?? r.industry ?? "—")}</td>
                <td className="mono">{fmtNum(r.members)}</td>
                <td className="mono">
                  {r.weight != null ? `${(Number(r.weight) * 100).toFixed(1)}%` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pagination
          page={indPag.page}
          pageSize={indPag.pageSize}
          total={indPag.total}
          onChange={indPag.setPage}
        />
        {!data.industry?.length && <p className="muted">暂无行业分布</p>}
      </div>
    </div>
  );
}
