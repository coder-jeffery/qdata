import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";
import { pollJob } from "../shared/useJobPoll";
import { useToast } from "../shared/Toast";

export function ExperimentsPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const list = useAsync(() => api.experiments(40), []);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useAsync(
    () => (selected ? api.experiment(selected) : Promise.resolve(null)),
    [selected],
  );
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  if (list.loading) return <div className="content muted">载入中…</div>;
  if (list.err) return <div className="content err">{list.err}</div>;

  const items = list.data?.items || [];

  async function paperFromExp() {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api.paperFromExperiment(selected, "sharpe");
      let sid = "";
      if (r.async && r.job_id) {
        toast.info(`挂钩排队 · ${r.job_id}`);
        const job = await pollJob(r.job_id, { timeoutMs: 180_000 });
        if (job.status === "failed") throw new Error(job.error || "挂钩失败");
        sid = String((job.result as { session_id?: string } | null)?.session_id || "");
      } else {
        sid = String((r.result as { session_id?: string } | undefined)?.session_id || "");
      }
      toast.ok(sid ? `已创建 Paper 会话 ${sid}` : "已完成 paper-from-experiment");
      if (sid) navigate(`/paper?session=${encodeURIComponent(sid)}`);
    } catch (e) {
      toast.err((e as Error).message);
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  return (
    <div className="content">
      <ConfirmDialog
        open={confirm}
        title="实验最优 cell → Paper？"
        body={`将按夏普选优并调仓生成新 Paper 会话。实验：${selected || ""}`}
        confirmLabel="确认调仓"
        busy={busy}
        onCancel={() => setConfirm(false)}
        onConfirm={paperFromExp}
      />

      <div className="panel">
        <h3>实验列表</h3>
        {!items.length ? (
          <p className="muted">暂无实验。请先跑实验矩阵 CLI。</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>实验 ID</th>
                <th>创建时间</th>
                <th>版本</th>
                <th>格子</th>
                <th>成功/失败</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr
                  key={e.experiment_id}
                  style={{
                    cursor: "pointer",
                    background: selected === e.experiment_id ? "var(--accent-dim)" : undefined,
                  }}
                  onClick={() => setSelected(e.experiment_id)}
                >
                  <td className="mono">{e.experiment_id}</td>
                  <td className="mono">{String(e.created_at || "—").slice(0, 19)}</td>
                  <td className="mono">{e.dataset_version || "—"}</td>
                  <td className="mono">{e.n_cells ?? "—"}</td>
                  <td className="mono">
                    <span className="up">{e.n_ok ?? 0}</span> /{" "}
                    <span className="down">{e.n_fail ?? 0}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && (
        <div className="panel">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>实验明细 · {selected}</h3>
            <button type="button" className="btn primary" disabled={busy} onClick={() => setConfirm(true)}>
              最优 cell → Paper
            </button>
          </div>
          {detail.loading && <p className="muted">载入明细…</p>}
          {detail.err && <p className="err">{detail.err}</p>}
          {detail.data && (
            <table className="data" style={{ marginTop: 14 }}>
              <thead>
                <tr>
                  <th>因子</th>
                  <th>加权</th>
                  <th>夏普</th>
                  <th>年化</th>
                  <th>回撤</th>
                  <th>状态</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {(detail.data.summary || []).map((row, i) => (
                  <tr key={i}>
                    <td className="mono">{String(row.factor ?? "—")}</td>
                    <td>{String(row.weight_method ?? "—")}</td>
                    <td className="mono">{row.sharpe != null ? Number(row.sharpe).toFixed(2) : "—"}</td>
                    <td className="mono">
                      {row.ann_return != null
                        ? `${(Number(row.ann_return) * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className="mono down">
                      {row.max_drawdown != null
                        ? `${(Number(row.max_drawdown) * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td>{String(row.status ?? "—")}</td>
                    <td>
                      {row.run_id ? (
                        <button
                          type="button"
                          className="btn ghost"
                          style={{ minHeight: 30, padding: "0 10px" }}
                          onClick={() =>
                            navigate(`/research/backtests/${encodeURIComponent(String(row.run_id))}`)
                          }
                        >
                          回测
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted" style={{ marginTop: 8 }}>
            cells: {fmtNum(detail.data?.meta?.n_cells)}
          </p>
        </div>
      )}
    </div>
  );
}
