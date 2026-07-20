import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Overview } from "../api/types";
import { Pagination } from "../shared/Pagination";
import { fmtNum, pnlClass } from "../shared/format";
import { usePagination } from "../shared/usePagination";

export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .overview()
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e: Error) => {
        if (alive) setErr(e.message);
      });
    return () => {
      alive = false;
    };
  }, []);

  const paper = data?.paper;
  const paperRows = useMemo(() => {
    if (!paper?.session_id) return [];
    return [
      { k: "会话", v: paper.session_id },
      { k: "As-of", v: paper.asof ?? "—" },
      { k: "可用现金", v: fmtNum(paper.cash) },
      { k: "市值", v: fmtNum(paper.market_value) },
      {
        k: "成交 / 拒单",
        v: `${paper.n_filled ?? 0} / ${paper.n_rejected ?? 0}`,
      },
      { k: "盯市日", v: paper.mark_date ?? "—" },
    ];
  }, [paper]);
  const paperPag = usePagination(paperRows, 20);

  if (err) {
    return (
      <div className="content">
        <p className="err">无法加载总览：{err}</p>
        <p className="muted">请先启动 BFF：python -m qdata.jobs.web_api</p>
      </div>
    );
  }

  if (!data) {
    return <div className="content muted">载入中…</div>;
  }

  const bar = data.daily_bar;
  const mon = data.factor_monitor;

  return (
    <div className="content">
      <div className="cards">
        <div className="card">
          <div className="k">数据集版本</div>
          <div className="v mono">{data.dataset.version ?? "—"}</div>
          <div className="s">{data.dataset.source ?? "—"}</div>
        </div>
        <div className="card">
          <div className="k">日线水位</div>
          <div className="v mono">{bar.max_date ?? "—"}</div>
          <div className="s">
            {bar.n_codes != null ? `${fmtNum(bar.n_codes)} 只 · ${fmtNum(bar.days)} 日` : bar.error ?? "—"}
          </div>
        </div>
        <div className="card">
          <div className="k">因子告警</div>
          <div className={`v mono ${Number(mon.n_alerts) > 0 ? "down" : ""}`}>
            {mon.n_alerts ?? 0}
          </div>
          <div className="s">
            {mon.date ?? "—"} · {mon.via === "daily_run" ? "日批" : mon.via ?? "—"}
          </div>
        </div>
        <div className="card">
          <div className="k">Paper 总资产</div>
          <div className="v mono">{fmtNum(paper?.total_asset, 0)}</div>
          <div className="s">
            <span className={pnlClass(paper?.pnl_vs_initial)}>
              {paper?.pnl_vs_initial != null
                ? `${Number(paper.pnl_vs_initial) >= 0 ? "+" : ""}${fmtNum(paper.pnl_vs_initial, 0)}`
                : "—"}
            </span>
            {" · "}
            {paper?.session_id?.slice(0, 18) ?? "无会话"}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>快捷入口</h3>
        <div className="btn-row">
          <Link className="btn primary" to="/paper">
            Paper 运营
          </Link>
          <Link className="btn ghost" to="/trade">
            交易台
          </Link>
          <Link className="btn ghost" to="/data/health">
            数据健康
          </Link>
          <Link className="btn ghost" to="/data/finance">
            财务 PIT
          </Link>
          <Link className="btn ghost" to="/research/experiments">
            实验矩阵
          </Link>
          <Link className="btn ghost" to="/research/signals">
            信号台
          </Link>
        </div>
      </div>

      <div className="panel">
        <h3>Paper 摘要</h3>
        {paper?.session_id ? (
          <>
            <table className="data">
              <tbody>
                {paperPag.view.map((r) => (
                  <tr key={r.k}>
                    <td>{r.k}</td>
                    <td className="mono">{r.v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={paperPag.page}
              pageSize={paperPag.pageSize}
              total={paperPag.total}
              onChange={paperPag.setPage}
            />
          </>
        ) : (
          <p className="muted">暂无 Paper 会话。先运行 paper_rebalance。</p>
        )}
      </div>
    </div>
  );
}
