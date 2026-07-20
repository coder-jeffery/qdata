import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api, type AlertItem, type JobRecord } from "../api/client";
import { Pagination } from "../shared/Pagination";
import { usePagination } from "../shared/usePagination";

const titles: Record<string, { title: string; sub: string }> = {
  "/": { title: "运营总览", sub: "日批水位 · 监控 · Paper 摘要" },
  "/trade": { title: "交易台", sub: "Paper 只读 · 持仓 / 成交 · 实时叠加" },
  "/chart": { title: "技术图", sub: "K线 · MA · MACD · KDJ · 布林带" },
  "/research": { title: "研究工作台", sub: "回测矩阵 · 研究入口" },
  "/research/experiments": { title: "实验矩阵", sub: "Lake experiments" },
  "/research/signals": { title: "信号台", sub: "权重 · TopN 研判" },
  "/research/factors": { title: "因子覆盖", sub: "factor_value 覆盖率" },
  "/research/universe": { title: "选股域 / 行业", sub: "指数成分 · 行业分布" },
  "/research/judgment": { title: "个股研判", sub: "JudgmentCard · 实时" },
  "/data/health": { title: "数据健康", sub: "水位 · 发布 · 滞后" },
  "/data/finance": { title: "财务 PIT", sub: "公告水位 · 科目覆盖" },
  "/ops/monitor": { title: "因子监控", sub: "factor_monitor 报告" },
  "/ops/jobs": { title: "异步任务", sub: "web_jobs 队列" },
  "/paper": { title: "Paper 运营", sub: "会话 · 盯市 · 对比" },
};

function titleFor(path: string) {
  if (path.startsWith("/chart/")) {
    return { title: "技术图", sub: path.split("/").pop() || "" };
  }
  if (path.startsWith("/research/judgment/")) {
    return { title: "个股研判", sub: path.split("/").pop() || "" };
  }
  if (path.startsWith("/research/backtests/")) {
    return { title: "回测详情", sub: path.split("/").pop() || "" };
  }
  return titles[path] ?? { title: "qdata", sub: "" };
}

export function Layout() {
  const { pathname } = useLocation();
  const meta = titleFor(pathname);
  const fullBleed = pathname === "/trade" || pathname === "/chart" || pathname.startsWith("/chart/");

  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [nError, setNError] = useState(0);
  const [nWarn, setNWarn] = useState(0);
  const [alertOpen, setAlertOpen] = useState(false);
  const [activeJobs, setActiveJobs] = useState<JobRecord[]>([]);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      api
        .alerts()
        .then((d) => {
          if (!alive) return;
          setAlerts(d.items || []);
          setNError(d.n_error || 0);
          setNWarn(d.n_warn || 0);
        })
        .catch(() => {});
      api
        .jobs(20)
        .then((d) => {
          if (!alive) return;
          setActiveJobs(
            (d.items || []).filter((j) => j.status === "queued" || j.status === "running"),
          );
        })
        .catch(() => {});
    };
    tick();
    const id = window.setInterval(tick, 12_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const badge = nError + nWarn;
  const alertPag = usePagination(alerts, 10);

  return (
    <div className="shell">
      <aside className="nav" aria-label="主导航">
        <div className="logo">
          <strong>qdata</strong>
          <em>Desk</em>
        </div>

        <div className="nav-sec">工作台</div>
        <NavLink to="/" end className={({ isActive }) => (isActive ? "on" : "")}>
          总览
        </NavLink>
        <NavLink to="/trade" className={({ isActive }) => (isActive ? "on" : "")}>
          交易台
        </NavLink>
        <NavLink to="/research" end className={({ isActive }) => (isActive ? "on" : "")}>
          研究
        </NavLink>
        <NavLink to="/chart" className={({ isActive }) => (isActive ? "on" : "")}>
          技术图
        </NavLink>

        <div className="nav-sec">数据运维</div>
        <NavLink to="/data/health" className={({ isActive }) => (isActive ? "on" : "")}>
          数据健康
        </NavLink>
        <NavLink to="/data/finance" className={({ isActive }) => (isActive ? "on" : "")}>
          财务 PIT
        </NavLink>
        <NavLink to="/ops/monitor" className={({ isActive }) => (isActive ? "on" : "")}>
          因子监控
        </NavLink>
        <NavLink to="/ops/jobs" className={({ isActive }) => (isActive ? "on" : "")}>
          异步任务
        </NavLink>
        <NavLink to="/research/factors" className={({ isActive }) => (isActive ? "on" : "")}>
          因子覆盖
        </NavLink>

        <div className="nav-sec">研究决策</div>
        <NavLink to="/research/experiments" className={({ isActive }) => (isActive ? "on" : "")}>
          实验矩阵
        </NavLink>
        <NavLink to="/research/signals" className={({ isActive }) => (isActive ? "on" : "")}>
          信号台
        </NavLink>
        <NavLink to="/research/universe" className={({ isActive }) => (isActive ? "on" : "")}>
          选股域
        </NavLink>
        <NavLink to="/research/judgment" className={({ isActive }) => (isActive ? "on" : "")}>
          个股研判
        </NavLink>

        <div className="nav-sec">纸交易</div>
        <NavLink to="/paper" className={({ isActive }) => (isActive ? "on" : "")}>
          Paper
        </NavLink>

        <div className="nav-foot">
          <div className="acct">
            <div className="lbl">当前环境</div>
            <div className="name">Local · BFF</div>
            <div className="bal mono">:8787 → /api</div>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="top">
          <h1>{meta.title}</h1>
          <span className="sub">{meta.sub}</span>
          <div className="top-actions">
            {activeJobs.length > 0 && (
              <Link to="/ops/jobs" className="job-pill" title="进行中的任务">
                <span className="job-dot" />
                {activeJobs.length} 任务
              </Link>
            )}
            <div className="alert-wrap">
              <button
                type="button"
                className={`alert-bell ${badge ? "has" : ""} ${nError ? "err" : ""}`}
                aria-label="告警中心"
                onClick={() => setAlertOpen((v) => !v)}
              >
                告警
                {badge > 0 && <span className="alert-badge">{badge > 9 ? "9+" : badge}</span>}
              </button>
              {alertOpen && (
                <div className="alert-panel" role="dialog" aria-label="告警列表">
                  <div className="alert-panel-hd">
                    <strong>告警中心</strong>
                    <span className="muted">
                      {nError} 错误 · {nWarn} 警告
                    </span>
                  </div>
                  {!alerts.length ? (
                    <p className="muted" style={{ padding: "12px 14px" }}>
                      当前无告警
                    </p>
                  ) : (
                    <>
                      <ul className="alert-list">
                        {alertPag.view.map((a) => (
                          <li key={a.id} className={a.level === "error" ? "lvl-err" : "lvl-warn"}>
                            {a.href ? (
                              <Link to={a.href} onClick={() => setAlertOpen(false)}>
                                <div className="t">{a.title}</div>
                                <div className="m">{a.message}</div>
                              </Link>
                            ) : (
                              <>
                                <div className="t">{a.title}</div>
                                <div className="m">{a.message}</div>
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                      <div style={{ padding: "0 12px 10px" }}>
                        <Pagination
                          page={alertPag.page}
                          pageSize={alertPag.pageSize}
                          total={alertPag.total}
                          onChange={alertPag.setPage}
                        />
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </header>
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            overflow: fullBleed ? "hidden" : "auto",
          }}
        >
          <Outlet />
        </div>
      </div>
    </div>
  );
}
