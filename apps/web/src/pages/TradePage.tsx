import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type QuoteRow } from "../api/client";
import type { PaperSessionDetail, PaperSessionMeta } from "../api/types";
import { Pagination } from "../shared/Pagination";
import { fmtNum, pnlClass } from "../shared/format";
import { pollJob } from "../shared/useJobPoll";
import { usePagination } from "../shared/usePagination";
import { useToast } from "../shared/Toast";

export function TradePage() {
  const toast = useToast();
  const [params] = useSearchParams();
  const [sessions, setSessions] = useState<PaperSessionMeta[]>([]);
  const [sid, setSid] = useState<string>("");
  const [detail, setDetail] = useState<PaperSessionDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [quotes, setQuotes] = useState<Record<string, QuoteRow>>({});
  const [snapTs, setSnapTs] = useState<string | null>(null);
  const [rtBusy, setRtBusy] = useState(false);

  const positions = detail?.positions || [];
  const orders = detail?.orders || [];
  const posPag = usePagination(positions, 20, sid);
  const ordPag = usePagination(orders, 20, sid);

  useEffect(() => {
    const focus = params.get("session");
    api
      .paperSessions(100)
      .then((d) => {
        setSessions(d.items);
        setSid(focus || d.items[0]?.session_id || "");
      })
      .catch((e: Error) => setErr(e.message));
  }, [params]);

  useEffect(() => {
    if (!sid) return;
    api
      .paperSession(sid)
      .then(setDetail)
      .catch((e: Error) => setErr(e.message));
  }, [sid]);

  const pnl = detail?.mark_latest?.pnl_vs_initial ?? detail?.meta?.last_mark_pnl_vs_initial;

  const codes = useMemo(
    () =>
      positions
        .map((p) => String(p.exchange_code ?? p.ts_code ?? "").toUpperCase())
        .filter(Boolean),
    [positions],
  );

  useEffect(() => {
    if (!codes.length) {
      setQuotes({});
      return;
    }
    let alive = true;
    const load = () => {
      api
        .realtimeQuotes(codes)
        .then((d) => {
          if (!alive) return;
          const map: Record<string, QuoteRow> = {};
          for (const q of d.quotes || []) {
            const c = String(q.exchange_code || "").toUpperCase();
            if (c) map[c] = q;
          }
          setQuotes(map);
          setSnapTs(d.snapshot_ts ? String(d.snapshot_ts) : null);
        })
        .catch(() => {});
    };
    load();
    const id = window.setInterval(load, 30_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [codes.join(",")]);

  async function refreshRealtime() {
    if (!codes.length) {
      toast.info("当前无持仓代码可刷新");
      return;
    }
    setRtBusy(true);
    try {
      const r = await api.realtimeRefresh(codes);
      if (r.job_id) {
        toast.info(`实时刷新排队 · ${r.job_id}`);
        const job = await pollJob(r.job_id, { timeoutMs: 60_000 });
        if (job.status === "failed") throw new Error(job.error || "刷新失败");
      }
      const d = await api.realtimeQuotes(codes);
      const map: Record<string, QuoteRow> = {};
      for (const q of d.quotes || []) {
        const c = String(q.exchange_code || "").toUpperCase();
        if (c) map[c] = q;
      }
      setQuotes(map);
      setSnapTs(d.snapshot_ts ? String(d.snapshot_ts) : null);
      toast.ok(`已叠加实时行情 ${Object.keys(map).length} 只`);
    } catch (e) {
      toast.err((e as Error).message);
    } finally {
      setRtBusy(false);
    }
  }

  const watch = useMemo(() => {
    return positions.map((p) => {
      const code = String(p.exchange_code ?? p.ts_code ?? "—");
      const name = String(p.name ?? p.security_name ?? p.stock_name ?? "");
      const q = quotes[code.toUpperCase()];
      const price = q?.price != null && q.price !== "" ? Number(q.price) : null;
      const pre = q?.pre_close != null && q.pre_close !== "" ? Number(q.pre_close) : null;
      const chg = price != null && pre != null && pre !== 0 ? (price - pre) / pre : null;
      return {
        code,
        name: name && name !== "—" ? name : "",
        qty: p.qty ?? p.quantity,
        mv: p.market_value ?? p.mv,
        price,
        chg,
      };
    });
  }, [positions, quotes]);

  if (err) {
    return (
      <div className="content">
        <p className="err">{err}</p>
        <p className="muted">请先启动 BFF，并确保有 Paper 会话。</p>
      </div>
    );
  }

  return (
    <div className="trade-layout" style={{ flex: 1, minHeight: 0 }}>
      <div className="trade-main">
        <div className="trade-banner">
          <div className="banner warn" style={{ marginBottom: 0 }}>
            Paper 只读交易台 · 展示会话持仓/成交，不接真金委托。完整写操作请到{" "}
            <Link to="/paper" style={{ color: "var(--accent-hi)" }}>
              Paper 运营
            </Link>
            。
          </div>
        </div>

        <div className="watch">
          {watch.length === 0 ? (
            <span className="muted" style={{ padding: "8px 0" }}>
              当前会话无持仓
            </span>
          ) : (
            watch.map((w) => (
              <div key={w.code} className="wchip on">
                <div className="c mono">{w.code}</div>
                {w.name ? <div className="n">{w.name}</div> : null}
                <div className={`p mono ${w.chg != null ? (w.chg >= 0 ? "up" : "down") : ""}`}>
                  {w.price != null ? fmtNum(w.price, 2) : fmtNum(w.mv)}
                </div>
                {w.chg != null && (
                  <div className={`muted mono ${w.chg >= 0 ? "up" : "down"}`} style={{ fontSize: 10 }}>
                    {`${w.chg >= 0 ? "+" : ""}${(w.chg * 100).toFixed(2)}%`}
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        <div className="chart-zone">
          <div className="chart-zone-head">
            <strong style={{ fontSize: 14 }}>会话净值</strong>
            <span className="mono" style={{ fontSize: 20 }}>
              {fmtNum(detail?.account?.total_asset)}
            </span>
            <span className={pnlClass(pnl)}>
              {pnl != null ? `${Number(pnl) >= 0 ? "+" : ""}${fmtNum(pnl)}` : "—"}
            </span>
            <span className="muted">asof {detail?.meta?.asof || "—"}</span>
          </div>
          <div className="chart">
            <div className="chart-tag">Paper · Positions MV</div>
            <svg viewBox="0 0 900 96" preserveAspectRatio="none">
              <defs>
                <linearGradient id="area2" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8EC4D4" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#8EC4D4" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path
                fill="url(#area2)"
                d="M40,62 C160,55 220,70 340,48 C460,30 520,38 640,28 C760,20 820,24 860,18 L860,96 L40,96 Z"
              />
              <path
                fill="none"
                stroke="#B0DBE8"
                strokeWidth="2"
                d="M40,62 C160,55 220,70 340,48 C460,30 520,38 640,28 C760,20 820,24 860,18"
              />
            </svg>
          </div>
        </div>

        <div className="strip">
          <section>
            <h3 style={{ marginBottom: 10 }}>持仓</h3>
            <table className="data">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>代码</th>
                  <th>数量</th>
                  <th>市值</th>
                  <th>现价</th>
                </tr>
              </thead>
              <tbody>
                {posPag.view.map((p, i) => {
                  const code = String(p.exchange_code ?? p.ts_code ?? "—");
                  const name = String(p.name ?? p.security_name ?? p.stock_name ?? "—");
                  const q = quotes[code.toUpperCase()];
                  const price = q?.price != null && q.price !== "" ? Number(q.price) : null;
                  return (
                    <tr key={i}>
                      <td>{name}</td>
                      <td className="mono">{code}</td>
                      <td className="mono">{fmtNum(p.qty ?? p.quantity)}</td>
                      <td className="mono">{fmtNum(p.market_value ?? p.mv)}</td>
                      <td className="mono">{price != null ? fmtNum(price, 2) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pagination
              page={posPag.page}
              pageSize={posPag.pageSize}
              total={posPag.total}
              onChange={posPag.setPage}
            />
          </section>
          <section>
            <h3 style={{ marginBottom: 10 }}>成交</h3>
            <table className="data">
              <thead>
                <tr>
                  <th>代码</th>
                  <th>方向</th>
                  <th>数量</th>
                  <th>价格</th>
                </tr>
              </thead>
              <tbody>
                {ordPag.view.map((o, i) => (
                  <tr key={i}>
                    <td className="mono">{String(o.exchange_code ?? o.ts_code ?? "—")}</td>
                    <td>{String(o.side ?? o.direction ?? "—")}</td>
                    <td className="mono">{fmtNum(o.qty ?? o.quantity)}</td>
                    <td className="mono">{fmtNum(o.price ?? o.fill_price, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={ordPag.page}
              pageSize={ordPag.pageSize}
              total={ordPag.total}
              onChange={ordPag.setPage}
            />
          </section>
        </div>
      </div>

      <div className="trade-rail">
        <div className="rail-sec">
          <h3 style={{ marginBottom: 12 }}>Paper 会话</h3>
          <div className="field">
            <label>选择会话</label>
            <select
              className="btn ghost"
              style={{ width: "100%", textAlign: "left" }}
              value={sid}
              onChange={(e) => setSid(e.target.value)}
            >
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.session_id}
                </option>
              ))}
            </select>
          </div>
          <div className="cards" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 0 }}>
            <div className="card">
              <div className="k">现金</div>
              <div className="v" style={{ fontSize: 15 }}>
                {fmtNum(detail?.account?.cash)}
              </div>
            </div>
            <div className="card">
              <div className="k">市值</div>
              <div className="v" style={{ fontSize: 15 }}>
                {fmtNum(detail?.account?.market_value)}
              </div>
            </div>
          </div>
        </div>
        <div className="rail-sec">
          <h3 style={{ marginBottom: 12 }}>实时叠加</h3>
          <p className="muted" style={{ marginBottom: 10, lineHeight: 1.5 }}>
            Lake `realtime` 通道 · {snapTs ? `快照 ${snapTs}` : "暂无快照"}
          </p>
          <button
            type="button"
            className="btn ghost"
            style={{ width: "100%", marginBottom: 12 }}
            disabled={rtBusy || !codes.length}
            onClick={refreshRealtime}
          >
            {rtBusy ? "刷新中…" : "拉取实时行情"}
          </button>
          <h3 style={{ marginBottom: 12 }}>操作</h3>
          <div className="btn-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
            <Link className="btn primary" to="/paper">
              去盯市 / 对比
            </Link>
            <Link className="btn ghost" to="/research/signals">
              信号台
            </Link>
          </div>
          <p className="muted" style={{ marginTop: 12, lineHeight: 1.55 }}>
            成交 {orders.length} · 拒单 {detail?.rejects?.length ?? 0} · 持仓{" "}
            {positions.length}
          </p>
        </div>
      </div>
    </div>
  );
}
