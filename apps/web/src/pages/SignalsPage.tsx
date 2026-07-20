import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { Pagination } from "../shared/Pagination";
import { fmtNum } from "../shared/format";
import { useAsync } from "../shared/useAsync";
import { pollJob } from "../shared/useJobPoll";
import { usePagination } from "../shared/usePagination";
import { useToast } from "../shared/Toast";

export function SignalsPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const list = useAsync(() => api.signals(100), []);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useAsync(
    () => (selected ? api.signal(selected) : Promise.resolve(null)),
    [selected],
  );
  const [cards, setCards] = useState<Array<Record<string, unknown>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const items = list.data?.items || [];
  const weights = detail.data?.weights || [];
  const listPag = usePagination(items, 20);
  const weightPag = usePagination(weights, 20, selected);
  const cardPag = usePagination(cards || [], 20, cards?.length ?? 0);

  async function runJudge() {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api.signalJudge(selected, 20);
      if (r.async && r.job_id) {
        toast.info(`研判排队 · ${r.job_id}`);
        const job = await pollJob(r.job_id);
        if (job.status === "failed") throw new Error(job.error || "研判失败");
        const result = (job.result || {}) as {
          n?: number;
          cards?: Array<Record<string, unknown>>;
        };
        setCards(result.cards || []);
        toast.ok(`已研判 ${result.n ?? 0} 只`);
      } else {
        setCards(r.cards || []);
        toast.ok(`已研判 ${r.n} 只`);
      }
    } catch (e) {
      toast.err((e as Error).message);
    } finally {
      setBusy(false);
      setConfirm(false);
    }
  }

  if (list.loading) return <div className="content muted">载入中…</div>;
  if (list.err) return <div className="content err">{list.err}</div>;

  return (
    <div className="content">
      <ConfirmDialog
        open={confirm}
        title="对信号 Top20 批量研判？"
        body="将调用 judge_signal_topn，可能查询 ClickHouse，耗时取决于因子覆盖。"
        confirmLabel="开始研判"
        busy={busy}
        onCancel={() => setConfirm(false)}
        onConfirm={runJudge}
      />

      <div className="panel">
        <h3>信号列表</h3>
        {!items.length ? (
          <p className="muted">暂无信号。请先 build_signal。</p>
        ) : (
          <>
            <table className="data">
              <thead>
                <tr>
                  <th>信号 ID</th>
                  <th>As-of</th>
                  <th>因子</th>
                  <th>加权</th>
                  <th>宇宙</th>
                  <th>TopN</th>
                </tr>
              </thead>
              <tbody>
                {listPag.view.map((s) => {
                  const key = s.signal_id || s.path || "";
                  return (
                    <tr
                      key={key}
                      style={{
                        cursor: "pointer",
                        background: selected === key ? "var(--accent-dim)" : undefined,
                      }}
                      onClick={() => {
                        setSelected(key);
                        setCards(null);
                      }}
                    >
                      <td className="mono">{s.signal_id}</td>
                      <td className="mono">{s.asof || "—"}</td>
                      <td className="mono">{s.factor || "—"}</td>
                      <td>{s.weight_method || "—"}</td>
                      <td className="mono">{s.universe || "—"}</td>
                      <td className="mono">{s.top_n ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pagination
              page={listPag.page}
              pageSize={listPag.pageSize}
              total={listPag.total}
              onChange={listPag.setPage}
            />
          </>
        )}
      </div>

      {selected && (
        <div className="panel">
          <div className="btn-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>权重 Top · {selected}</h3>
            <div className="btn-row">
              <button type="button" className="btn primary" disabled={busy} onClick={() => setConfirm(true)}>
                Top20 研判
              </button>
              <Link className="btn ghost" to="/paper">
                去 Paper
              </Link>
            </div>
          </div>
          {detail.loading && <p className="muted">载入权重…</p>}
          {detail.err && <p className="err">{detail.err}</p>}
          {detail.data && (
            <>
              <table className="data">
                <thead>
                  <tr>
                    <th>代码</th>
                    <th>权重</th>
                    <th>行业</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {weightPag.view.map((w, i) => {
                    const code = String(w.exchange_code ?? w.ts_code ?? "—");
                    return (
                      <tr key={i}>
                        <td className="mono">{code}</td>
                        <td className="mono">
                          {w.weight != null ? Number(w.weight).toFixed(4) : "—"}
                        </td>
                        <td>{String(w.industry ?? w.sw_l1 ?? "—")}</td>
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
              <Pagination
                page={weightPag.page}
                pageSize={weightPag.pageSize}
                total={weightPag.total}
                onChange={weightPag.setPage}
              />
            </>
          )}
        </div>
      )}

      {cards && (
        <div className="panel">
          <h3>研判卡片</h3>
          <table className="data">
            <thead>
              <tr>
                <th>代码</th>
                <th>立场</th>
                <th>综合分</th>
                <th>相对强度</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {cardPag.view.map((r, i) => {
                const code = String(r.code ?? "—");
                return (
                  <tr key={i}>
                    <td className="mono">{code}</td>
                    <td>{String(r.stance ?? "—")}</td>
                    <td className="mono">
                      {r.composite != null ? Number(r.composite).toFixed(1) : "—"}
                    </td>
                    <td className="mono">
                      {r.relative_strength != null
                        ? `${(Number(r.relative_strength) * 100).toFixed(1)}%`
                        : "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn ghost"
                        style={{ minHeight: 30, padding: "0 10px" }}
                        onClick={() => navigate(`/research/judgment/${encodeURIComponent(code)}`)}
                      >
                        详情
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination
            page={cardPag.page}
            pageSize={cardPag.pageSize}
            total={cardPag.total}
            onChange={cardPag.setPage}
          />
          <p className="muted" style={{ marginTop: 8 }}>
            共 {fmtNum(cards.length)} 张
          </p>
        </div>
      )}
    </div>
  );
}
