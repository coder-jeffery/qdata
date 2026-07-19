import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import "../styles/chart.css";

type Bar = {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma5: number | null;
  ma10: number | null;
  boll_mid: number | null;
  boll_upper: number | null;
  boll_lower: number | null;
  dif: number | null;
  dea: number | null;
  macd_hist: number | null;
  k: number | null;
  d: number | null;
  j: number | null;
};

type TabId = "kline" | "boll" | "macd" | "kdj";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "kline", label: "K线" },
  { id: "boll", label: "布林带" },
  { id: "macd", label: "MACD" },
  { id: "kdj", label: "KDJ" },
];

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function scaleLinear(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

function linePath(
  ys: Array<number | null>,
  xAt: (i: number) => number,
  yAt: (v: number) => number,
): string {
  let d = "";
  let started = false;
  for (let i = 0; i < ys.length; i++) {
    const y = ys[i];
    if (y == null || Number.isNaN(y)) {
      started = false;
      continue;
    }
    d += `${started ? "L" : "M"}${xAt(i).toFixed(2)},${yAt(y).toFixed(2)} `;
    started = true;
  }
  return d.trim();
}

function yTicks(min: number, max: number, n = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return [min || 0];
  }
  const out: number[] = [];
  for (let i = 0; i <= n; i++) out.push(min + ((max - min) * i) / n);
  return out;
}

function parseTab(raw: string | null): TabId {
  if (raw === "boll" || raw === "macd" || raw === "kdj" || raw === "kline") return raw;
  return "kline";
}

export function ChartPage() {
  const { code: routeCode } = useParams();
  const [params, setParams] = useSearchParams();
  const [code, setCode] = useState(
    (routeCode || params.get("code") || "600519.SH").toUpperCase(),
  );
  const [start, setStart] = useState(params.get("start") || isoDaysAgo(180));
  const [end, setEnd] = useState(params.get("end") || todayIso());
  const [adjust, setAdjust] = useState<"post" | "pre" | "none">(
    (params.get("adjust") as "post" | "pre" | "none") || "post",
  );
  const [tab, setTab] = useState<TabId>(parseTab(params.get("tab")));
  const [bars, setBars] = useState<Bar[]>([]);
  const [meta, setMeta] = useState<{ start?: string; end?: string; last?: number | null }>({});
  const [hover, setHover] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = () => {
    const c = code.trim().toUpperCase();
    if (!c) return;
    setLoading(true);
    setErr(null);
    setParams({ code: c, start, end, adjust, tab });
    api
      .researchTa(c, { start, end, adjust })
      .then((d) => {
        setBars(d.bars || []);
        setMeta({ start: d.start, end: d.end, last: d.last_close });
        setCode(d.code);
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    const c = (routeCode || params.get("code") || "600519.SH").toUpperCase();
    const s = params.get("start") || isoDaysAgo(180);
    const e = params.get("end") || todayIso();
    const adj = (params.get("adjust") as "post" | "pre" | "none") || "post";
    setTab(parseTab(params.get("tab")));
    setLoading(true);
    setErr(null);
    api
      .researchTa(c, { start: s, end: e, adjust: adj })
      .then((d) => {
        setBars(d.bars || []);
        setMeta({ start: d.start, end: d.end, last: d.last_close });
        setCode(d.code);
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const switchTab = (id: TabId) => {
    setTab(id);
    setParams({ code, start, end, adjust, tab: id });
  };

  const n = bars.length;
  const hi = hover != null && hover >= 0 && hover < n ? bars[hover] : n ? bars[n - 1] : null;
  const prev = hi && hover != null && hover > 0 ? bars[hover - 1] : n > 1 ? bars[n - 2] : null;
  const upDay = hi && prev ? hi.close >= prev.close : true;

  const layout = useMemo(() => {
    const W = 1000;
    const H = 560;
    const padL = 54;
    const padR = 14;
    const padT = 32;
    const padB = 28;
    return { W, H, padL, padR, padT, padB, innerW: W - padL - padR };
  }, []);

  const xAt = (i: number) => {
    const { padL, innerW } = layout;
    if (n <= 1) return padL + innerW / 2;
    return padL + (i / (n - 1)) * innerW;
  };

  const priceChart = useMemo(() => {
    if (!n) return null;
    const { H, W, padT, padB } = layout;
    // K线视图底部留成交量带；布林带视图全高给价格
    const volBand = tab === "kline" ? 0.22 : 0;
    const priceBottom = padB + (H - padT - padB) * volBand;
    const highs = bars.map((b) => {
      let m = b.high;
      if (tab === "kline") m = Math.max(m, b.ma5 ?? m, b.ma10 ?? m);
      if (tab === "boll") m = Math.max(m, b.boll_upper ?? m);
      return m;
    });
    const lows = bars.map((b) => {
      let m = b.low;
      if (tab === "kline") m = Math.min(m, b.ma5 ?? m, b.ma10 ?? m);
      if (tab === "boll") m = Math.min(m, b.boll_lower ?? m);
      return m;
    });
    let ymin = Math.min(...lows);
    let ymax = Math.max(...highs);
    const pad = (ymax - ymin) * 0.06 || 1;
    ymin -= pad;
    ymax += pad;
    const yAt = scaleLinear([ymin, ymax], [H - priceBottom, padT]);
    const cw = Math.max(2, (layout.innerW / Math.max(n, 1)) * 0.62);
    const candles = bars.map((b, i) => {
      const x = xAt(i);
      const up = b.close >= b.open;
      const yO = yAt(b.open);
      const yC = yAt(b.close);
      return {
        i,
        x,
        up,
        wick: `M${x},${yAt(b.high)} L${x},${yAt(b.low)}`,
        body: {
          x: x - cw / 2,
          y: Math.min(yO, yC),
          w: cw,
          h: Math.max(1.2, Math.abs(yC - yO)),
        },
      };
    });

    let volume: Array<{ x: number; y: number; w: number; h: number; up: boolean }> | null = null;
    if (tab === "kline") {
      const vmax = Math.max(...bars.map((b) => b.volume), 1);
      const yV = scaleLinear([0, vmax], [H - padB, H - priceBottom + 6]);
      const bw = Math.max(1.5, (layout.innerW / Math.max(n, 1)) * 0.55);
      volume = bars.map((b, i) => {
        const x = xAt(i);
        const y = yV(b.volume);
        return {
          x: x - bw / 2,
          y,
          w: bw,
          h: H - padB - y,
          up: i === 0 ? true : b.close >= bars[i - 1].close,
        };
      });
    }

    return {
      H,
      W,
      yAt,
      ticks: yTicks(ymin, ymax),
      candles,
      ma5: linePath(
        bars.map((b) => b.ma5),
        xAt,
        yAt,
      ),
      ma10: linePath(
        bars.map((b) => b.ma10),
        xAt,
        yAt,
      ),
      bollU: linePath(
        bars.map((b) => b.boll_upper),
        xAt,
        yAt,
      ),
      bollM: linePath(
        bars.map((b) => b.boll_mid),
        xAt,
        yAt,
      ),
      bollL: linePath(
        bars.map((b) => b.boll_lower),
        xAt,
        yAt,
      ),
      volume,
      volSplitY: tab === "kline" ? H - priceBottom : null,
    };
  }, [bars, layout, n, tab]);

  const macdChart = useMemo(() => {
    if (!n || tab !== "macd") return null;
    const { H, W, padT, padB } = layout;
    const vals = bars
      .flatMap((b) => [b.dif, b.dea, b.macd_hist])
      .filter((v): v is number => v != null);
    let ymin = Math.min(...vals, 0);
    let ymax = Math.max(...vals, 0);
    if (ymin === ymax) {
      ymin -= 1;
      ymax += 1;
    }
    const yAt = scaleLinear([ymin, ymax], [H - padB, padT]);
    const bw = Math.max(1.2, (layout.innerW / Math.max(n, 1)) * 0.5);
    const zeroY = yAt(0);
    return {
      H,
      W,
      zeroY,
      ticks: yTicks(ymin, ymax),
      yAt,
      hist: bars.map((b, i) => {
        const v = b.macd_hist;
        if (v == null) return null;
        const y = yAt(v);
        return {
          x: xAt(i) - bw / 2,
          y: v >= 0 ? y : zeroY,
          w: bw,
          h: Math.max(1, Math.abs(y - zeroY)),
          up: v >= 0,
        };
      }),
      dif: linePath(
        bars.map((b) => b.dif),
        xAt,
        yAt,
      ),
      dea: linePath(
        bars.map((b) => b.dea),
        xAt,
        yAt,
      ),
    };
  }, [bars, layout, n, tab]);

  const kdjChart = useMemo(() => {
    if (!n || tab !== "kdj") return null;
    const { H, W, padT, padB } = layout;
    const yAt = scaleLinear([0, 100], [H - padB, padT]);
    return {
      H,
      W,
      yAt,
      marks: [20, 50, 80].map((v) => ({ v, y: yAt(v) })),
      k: linePath(
        bars.map((b) => b.k),
        xAt,
        yAt,
      ),
      d: linePath(
        bars.map((b) => b.d),
        xAt,
        yAt,
      ),
      j: linePath(
        bars.map((b) => b.j),
        xAt,
        yAt,
      ),
    };
  }, [bars, layout, n, tab]);

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    if (!n) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - rect.left) / rect.width;
    const i = Math.round(rel * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  const tipText = () => {
    if (!hi) return null;
    if (tab === "macd") {
      return `DIF ${hi.dif?.toFixed(3) ?? "—"}  DEA ${hi.dea?.toFixed(3) ?? "—"}  HIST ${hi.macd_hist?.toFixed(3) ?? "—"}`;
    }
    if (tab === "kdj") {
      return `K ${hi.k?.toFixed(1) ?? "—"}  D ${hi.d?.toFixed(1) ?? "—"}  J ${hi.j?.toFixed(1) ?? "—"}`;
    }
    if (tab === "boll") {
      return `${hi.trade_date}  C${hi.close.toFixed(2)}  U${hi.boll_upper?.toFixed(2) ?? "—"}  M${hi.boll_mid?.toFixed(2) ?? "—"}  L${hi.boll_lower?.toFixed(2) ?? "—"}`;
    }
    return `${hi.trade_date} O${hi.open.toFixed(2)} H${hi.high.toFixed(2)} L${hi.low.toFixed(2)} C${hi.close.toFixed(2)} V${hi.volume}`;
  };

  return (
    <div className="chart-desk">
      <div className="chart-top">
        <div className="chart-controls">
          <label>
            代码
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === "Enter" && load()}
            />
          </label>
          <label>
            开始
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            结束
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <label>
            复权
            <select value={adjust} onChange={(e) => setAdjust(e.target.value as typeof adjust)}>
              <option value="post">后复权</option>
              <option value="pre">前复权</option>
              <option value="none">不复权</option>
            </select>
          </label>
          <button type="button" onClick={load} disabled={loading}>
            {loading ? "载入中…" : "刷新"}
          </button>
        </div>
        <div className="chart-meta">
          <div className="code">{code}</div>
          <div className={`px ${upDay ? "up" : "down"}`}>
            {hi?.close != null ? hi.close.toFixed(2) : "—"}
          </div>
          <div className="hint">
            {meta.start && meta.end ? `${meta.start} → ${meta.end}` : ""} · {n} 根
          </div>
        </div>
      </div>

      <div className="chart-tabs" role="tablist" aria-label="指标视图">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? "on" : ""}
            onClick={() => switchTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {err && <div className="chart-err">{err}</div>}

      <div className="chart-stage single">
        <section className="chart-pane">
          {hi && <div className="chart-tip">{tipText()}</div>}

          {(tab === "kline" || tab === "boll") && priceChart && (
            <svg
              viewBox={`0 0 ${priceChart.W} ${priceChart.H}`}
              preserveAspectRatio="none"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              {priceChart.ticks.map((t) => (
                <g key={t}>
                  <line
                    className="grid-line"
                    x1={layout.padL}
                    x2={priceChart.W - layout.padR}
                    y1={priceChart.yAt(t)}
                    y2={priceChart.yAt(t)}
                  />
                  <text className="axis" x={4} y={priceChart.yAt(t) + 3}>
                    {t.toFixed(1)}
                  </text>
                </g>
              ))}
              {priceChart.volSplitY != null && (
                <line
                  className="grid-line"
                  x1={layout.padL}
                  x2={priceChart.W - layout.padR}
                  y1={priceChart.volSplitY}
                  y2={priceChart.volSplitY}
                />
              )}
              {tab === "boll" && (
                <>
                  <path d={priceChart.bollU} fill="none" stroke="rgba(168,180,196,0.45)" strokeWidth="1.2" />
                  <path
                    d={priceChart.bollM}
                    fill="none"
                    stroke="rgba(168,180,196,0.55)"
                    strokeWidth="1.2"
                    strokeDasharray="4 3"
                  />
                  <path d={priceChart.bollL} fill="none" stroke="rgba(168,180,196,0.45)" strokeWidth="1.2" />
                </>
              )}
              {tab === "kline" && (
                <>
                  <path d={priceChart.ma5} fill="none" stroke="#e0b35a" strokeWidth="1.5" />
                  <path d={priceChart.ma10} fill="none" stroke="#b0dbe8" strokeWidth="1.5" />
                </>
              )}
              {priceChart.candles.map((c) => (
                <g key={c.i}>
                  <path d={c.wick} stroke={c.up ? "#4ed68a" : "#f07178"} strokeWidth="1" />
                  <rect
                    x={c.body.x}
                    y={c.body.y}
                    width={c.body.w}
                    height={c.body.h}
                    fill={c.up ? "#4ed68a" : "#f07178"}
                  />
                </g>
              ))}
              {priceChart.volume?.map((b, i) => (
                <rect
                  key={`v${i}`}
                  x={b.x}
                  y={b.y}
                  width={b.w}
                  height={b.h}
                  fill={b.up ? "rgba(78,214,138,0.45)" : "rgba(240,113,120,0.45)"}
                />
              ))}
              {hover != null && (
                <line
                  x1={xAt(hover)}
                  x2={xAt(hover)}
                  y1={layout.padT}
                  y2={priceChart.H - layout.padB}
                  stroke="rgba(142,196,212,0.45)"
                  strokeDasharray="3 2"
                />
              )}
            </svg>
          )}

          {tab === "macd" && macdChart && (
            <svg
              viewBox={`0 0 ${macdChart.W} ${macdChart.H}`}
              preserveAspectRatio="none"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              {macdChart.ticks.map((t) => (
                <g key={t}>
                  <line
                    className="grid-line"
                    x1={layout.padL}
                    x2={macdChart.W - layout.padR}
                    y1={macdChart.yAt(t)}
                    y2={macdChart.yAt(t)}
                  />
                  <text className="axis" x={4} y={macdChart.yAt(t) + 3}>
                    {t.toFixed(2)}
                  </text>
                </g>
              ))}
              <line
                x1={layout.padL}
                x2={macdChart.W - layout.padR}
                y1={macdChart.zeroY}
                y2={macdChart.zeroY}
                stroke="rgba(142,196,212,0.35)"
              />
              {macdChart.hist.map(
                (h, i) =>
                  h && (
                    <rect
                      key={i}
                      x={h.x}
                      y={h.y}
                      width={h.w}
                      height={h.h}
                      fill={h.up ? "rgba(78,214,138,0.65)" : "rgba(240,113,120,0.65)"}
                    />
                  ),
              )}
              <path d={macdChart.dif} fill="none" stroke="#e0b35a" strokeWidth="1.5" />
              <path d={macdChart.dea} fill="none" stroke="#b0dbe8" strokeWidth="1.5" />
              {hover != null && (
                <line
                  x1={xAt(hover)}
                  x2={xAt(hover)}
                  y1={layout.padT}
                  y2={macdChart.H - layout.padB}
                  stroke="rgba(142,196,212,0.45)"
                  strokeDasharray="3 2"
                />
              )}
            </svg>
          )}

          {tab === "kdj" && kdjChart && (
            <svg
              viewBox={`0 0 ${kdjChart.W} ${kdjChart.H}`}
              preserveAspectRatio="none"
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            >
              {kdjChart.marks.map((m) => (
                <g key={m.v}>
                  <line
                    className="grid-line"
                    x1={layout.padL}
                    x2={kdjChart.W - layout.padR}
                    y1={m.y}
                    y2={m.y}
                  />
                  <text className="axis" x={4} y={m.y + 3}>
                    {m.v}
                  </text>
                </g>
              ))}
              <path d={kdjChart.k} fill="none" stroke="#e0b35a" strokeWidth="1.5" />
              <path d={kdjChart.d} fill="none" stroke="#b0dbe8" strokeWidth="1.5" />
              <path d={kdjChart.j} fill="none" stroke="#8ec4d4" strokeWidth="1.5" />
              {hover != null && (
                <line
                  x1={xAt(hover)}
                  x2={xAt(hover)}
                  y1={layout.padT}
                  y2={kdjChart.H - layout.padB}
                  stroke="rgba(142,196,212,0.45)"
                  strokeDasharray="3 2"
                />
              )}
            </svg>
          )}
        </section>
      </div>

      <div className="chart-foot">
        <div className="chart-legends">
          {tab === "kline" && (
            <>
              <span className="ma5">MA5</span>
              <span className="ma10">MA10</span>
              <span>成交量</span>
            </>
          )}
          {tab === "boll" && <span className="boll">BOLL 上/中/下轨</span>}
          {tab === "macd" && (
            <>
              <span className="ma5">DIF</span>
              <span className="ma10">DEA</span>
              <span>HIST</span>
            </>
          )}
          {tab === "kdj" && (
            <>
              <span className="ma5">K</span>
              <span className="ma10">D</span>
              <span>J</span>
            </>
          )}
          <span>绿涨红跌 · 日频 · {adjust}</span>
        </div>
        <div>
          <Link to={`/research/judgment/${encodeURIComponent(code)}`}>个股研判</Link>
        </div>
      </div>
    </div>
  );
}
