import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { PaperSessionDetail, PaperSessionMeta } from "../api/types";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { fmtNum, pnlClass } from "../shared/format";
import { pollJob } from "../shared/useJobPoll";
import { useToast } from "../shared/Toast";

export function PaperPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [items, setItems] = useState<PaperSessionMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareRows, setCompareRows] = useState<Array<Record<string, unknown>>>([]);
  const [detail, setDetail] = useState<PaperSessionDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmMark, setConfirmMark] = useState(false);

  async function reloadList(prefer?: string) {
    const d = await api.paperSessions(40);
    setItems(d.items);
    const next = prefer || selected || d.items[0]?.session_id || null;
    if (next) setSelected(next);
  }

  useEffect(() => {
    const focus = params.get("session");
    api
      .paperSessions(40)
      .then((d) => {
        setItems(d.items);
        setSelected(focus || d.items[0]?.session_id || null);
      })
      .catch((e: Error) => setErr(e.message));
  }, [params]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    api
      .paperSession(selected)
      .then(setDetail)
      .catch((e: Error) => setErr(e.message));
  }, [selected]);

  function toggleCompare(id: string) {
    setCompareIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-4),
    );
  }

  async function runCompare() {
    if (compareIds.length < 2) {
      toast.info("请至少勾选 2 个会话对比");
      return;
    }
    setBusy(true);
    try {
      const r = await api.paperCompare(compareIds);
      setCompareRows(r.items || []);
      toast.ok(`已对比 ${r.count} 个会话`);
    } catch (e) {
      toast.err((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runMark() {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api.paperMark(selected);
      if (r.async && r.job_id) {
        toast.info(`盯市排队 · ${r.job_id}`);
        const job = await pollJob(r.job_id, {
          onUpdate: (j) => {
            if (j.status === "running") toast.info("盯市执行中…");
          },
        });
        if (job.status === "failed") throw new Error(job.error || "盯市失败");
        const mark = (job.result || {}) as Record<string, unknown>;
        toast.ok(
          `盯市完成 · 总资产 ${fmtNum(mark.total_asset)} · 盈亏 ${fmtNum(mark.pnl_vs_initial)}`,
        );
      } else if (r.mark) {
        toast.ok(
          `盯市完成 · 总资产 ${fmtNum(r.mark.total_asset)} · 盈亏 ${fmtNum(r.mark.pnl_vs_initial)}`,
        );
      }
      setDetail(await api.paperSession(selected));
      await reloadList(selected);
    } catch (e) {
      toast.err((e as Error).message);
    } finally {
      setBusy(false);
      setConfirmMark(false);
    }
  }

  if (err) {
    return (
      <div className="content">
        <p className="err">{err}</p>
        <p className="muted">确认 BFF：python -m qdata.jobs.web_api</p>
      </div>
    );
  }

  return (
    <div className="content">
      <ConfirmDialog
        open={confirmMark}
        title="确认日终盯市？"
        body={`将对会话 ${selected || ""} 用收盘价重估持仓（不改变仓位与现金）。`}
        confirmLabel="执行盯市"
        busy={busy}
        onCancel={() => setConfirmMark(false)}
        onConfirm={runMark}
      />

      <div className="panel">
        <div className="btn-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>会话列表</h3>
          <div className="btn-row">
            <button type="button" className="btn ghost" disabled={busy} onClick={runCompare}>
              对比已选 ({compareIds.length})
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={busy || !selected}
              onClick={() => setConfirmMark(true)}
            >
              日终盯市
            </button>
            <button
              type="button"
              className="btn ghost"
              disabled={!selected}
              onClick={() => selected && navigate(`/trade?session=${encodeURIComponent(selected)}`)}
            >
              在交易台查看
            </button>
          </div>
        </div>
        {items.length === 0 ? (
          <p className="muted">暂无 Paper 会话</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>选</th>
                <th>会话</th>
                <th>As-of</th>
                <th>成交</th>
                <th>拒单</th>
                <th>盯市盈亏</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr
                  key={s.session_id}
                  style={{
                    cursor: "pointer",
                    background: selected === s.session_id ? "var(--accent-dim)" : undefined,
                  }}
                  onClick={() => setSelected(s.session_id)}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={compareIds.includes(s.session_id)}
                      onChange={() => toggleCompare(s.session_id)}
                    />
                  </td>
                  <td className="mono">{s.session_id}</td>
                  <td className="mono">{s.asof ?? "—"}</td>
                  <td className="mono">{s.n_filled ?? 0}</td>
                  <td className="mono">{s.n_rejected ?? 0}</td>
                  <td className={pnlClass(s.last_mark_pnl_vs_initial)}>
                    {s.last_mark_pnl_vs_initial != null
                      ? fmtNum(s.last_mark_pnl_vs_initial)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {compareRows.length > 0 && (
        <div className="panel">
          <h3>会话对比</h3>
          <table className="data">
            <thead>
              <tr>
                <th>会话</th>
                <th>总资产</th>
                <th>现金</th>
                <th>市值</th>
                <th>持仓</th>
                <th>盯市盈亏</th>
                <th>实验</th>
              </tr>
            </thead>
            <tbody>
              {compareRows.map((r, i) => (
                <tr key={i}>
                  <td className="mono">{String(r.session_id ?? "—")}</td>
                  <td className="mono">{fmtNum(r.total_asset)}</td>
                  <td className="mono">{fmtNum(r.cash)}</td>
                  <td className="mono">{fmtNum(r.market_value)}</td>
                  <td className="mono">{fmtNum(r.n_positions)}</td>
                  <td className={pnlClass(r.pnl_vs_initial)}>{fmtNum(r.pnl_vs_initial)}</td>
                  <td className="mono">{String(r.experiment_id ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <>
          <div className="cards">
            <div className="card">
              <div className="k">总资产</div>
              <div className="v">{fmtNum(detail.account.total_asset)}</div>
            </div>
            <div className="card">
              <div className="k">现金</div>
              <div className="v">{fmtNum(detail.account.cash)}</div>
            </div>
            <div className="card">
              <div className="k">市值</div>
              <div className="v">{fmtNum(detail.account.market_value)}</div>
            </div>
            <div className="card">
              <div className="k">持仓数</div>
              <div className="v">{detail.positions.length}</div>
            </div>
          </div>

          <div className="panel">
            <h3>持仓</h3>
            {detail.positions.length === 0 ? (
              <p className="muted">无持仓</p>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>数量</th>
                    <th>成本</th>
                    <th>市值</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {detail.positions.slice(0, 40).map((p, i) => {
                    const code = String(p.exchange_code ?? p.ts_code ?? "—");
                    return (
                      <tr key={code + i}>
                        <td className="mono">{code}</td>
                        <td className="mono">{fmtNum(p.qty ?? p.quantity)}</td>
                        <td className="mono">{fmtNum(p.cost_price ?? p.avg_cost, 2)}</td>
                        <td className="mono">{fmtNum(p.market_value ?? p.mv)}</td>
                        <td>
                          <button
                            type="button"
                            className="btn ghost"
                            style={{ minHeight: 30, padding: "0 10px" }}
                            onClick={() => navigate(`/research/judgment/${encodeURIComponent(code)}`)}
                          >
                            研判
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
