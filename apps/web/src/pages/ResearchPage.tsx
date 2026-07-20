import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Pagination } from "../shared/Pagination";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";
import { usePagination } from "../shared/usePagination";

export function ResearchPage() {
  const { data, err, loading } = useAsync(() => api.backtests(50), []);
  const matrix = data?.matrix || [];
  const pag = usePagination(matrix, 20);
  const best = matrix[0];

  return (
    <div className="content">
      <div className="cards" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div className="card">
          <div className="k">最近回测夏普</div>
          <div className={`v ${Number(best?.sharpe) >= 0 ? "up" : "down"}`}>
            {best?.sharpe != null ? Number(best.sharpe).toFixed(2) : "—"}
          </div>
          <div className="s">{best ? String(best.factor || best.run_id || "") : "暂无回测"}</div>
        </div>
        <div className="card">
          <div className="k">最大回撤</div>
          <div className="v down">
            {best?.max_drawdown != null
              ? `${(Number(best.max_drawdown) * 100).toFixed(1)}%`
              : "—"}
          </div>
          <div className="s">矩阵首行</div>
        </div>
        <div className="card">
          <div className="k">年化收益</div>
          <div className={`v ${Number(best?.ann_return) >= 0 ? "up" : "down"}`}>
            {best?.ann_return != null
              ? `${(Number(best.ann_return) * 100).toFixed(1)}%`
              : "—"}
          </div>
          <div className="s">共 {fmtNum(data?.count)} 条</div>
        </div>
      </div>

      {(err || data?.error) && <p className="muted">{err || data?.error}</p>}

      <div className="panel">
        <h3>研究入口</h3>
        <div className="btn-row">
          <Link className="btn primary" to="/research/experiments">
            实验矩阵
          </Link>
          <Link className="btn ghost" to="/research/signals">
            信号台
          </Link>
          <Link className="btn ghost" to="/research/universe">
            选股域
          </Link>
          <Link className="btn ghost" to="/research/judgment">
            个股研判
          </Link>
          <Link className="btn ghost" to="/chart/600519.SH">
            技术图面板
          </Link>
          <Link className="btn ghost" to="/research/factors">
            因子覆盖
          </Link>
          <Link className="btn ghost" to="/data/finance">
            财务 PIT
          </Link>
        </div>
      </div>

      <div className="panel">
        <h3>回测矩阵（最近）</h3>
        {loading && <p className="muted">载入中…</p>}
        {!loading && !matrix.length ? (
          <p className="muted">暂无回测 run</p>
        ) : (
          <>
            <table className="data">
              <thead>
                <tr>
                  <th>因子</th>
                  <th>宇宙</th>
                  <th>夏普</th>
                  <th>年化</th>
                  <th>回撤</th>
                  <th>run</th>
                </tr>
              </thead>
              <tbody>
                {pag.view.map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{String(r.factor ?? "—")}</td>
                    <td className="mono">{String(r.universe ?? "—")}</td>
                    <td className="mono">{r.sharpe != null ? Number(r.sharpe).toFixed(2) : "—"}</td>
                    <td className="mono">
                      {r.ann_return != null
                        ? `${(Number(r.ann_return) * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="mono down">
                      {r.max_drawdown != null
                        ? `${(Number(r.max_drawdown) * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td>
                      {r.run_id ? (
                        <Link
                          className="mono"
                          style={{ color: "var(--accent-hi)" }}
                          to={`/research/backtests/${encodeURIComponent(String(r.run_id))}`}
                        >
                          {String(r.run_id).slice(0, 18)}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={pag.page}
              pageSize={pag.pageSize}
              total={pag.total}
              onChange={pag.setPage}
            />
          </>
        )}
      </div>
    </div>
  );
}
