import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../shared/useAsync";

function statusClass(s: string) {
  if (s === "succeeded") return "up";
  if (s === "failed") return "down";
  return "muted";
}

export function JobsPage() {
  const { data, err, loading, reload } = useAsync(() => api.jobs(40), []);

  if (loading) return <div className="content muted">载入中…</div>;
  if (err) return <div className="content err">{err}</div>;

  const items = data?.items || [];

  return (
    <div className="content">
      <div className="panel">
        <div className="btn-row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>异步任务</h3>
          <button type="button" className="btn ghost" onClick={() => reload()}>
            刷新
          </button>
        </div>
        {!items.length ? (
          <p className="muted">暂无任务。盯市 / 研判 / 实验挂钩会写入 Lake web_jobs。</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>类型</th>
                <th>状态</th>
                <th>创建</th>
                <th>完成</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.job_id}>
                  <td className="mono">{j.job_id}</td>
                  <td className="mono">{j.type}</td>
                  <td className={statusClass(j.status)}>{j.status}</td>
                  <td className="mono">{String(j.created_at || "—").slice(0, 19)}</td>
                  <td className="mono">{String(j.finished_at || "—").slice(0, 19)}</td>
                  <td className="muted" style={{ maxWidth: 220 }}>
                    {j.error ? String(j.error).slice(0, 80) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ marginTop: 10 }}>
          失败任务也会出现在顶栏{" "}
          <Link to="/ops/monitor" style={{ color: "var(--accent-hi)" }}>
            告警
          </Link>{" "}
          聚合中。
        </p>
      </div>
    </div>
  );
}
