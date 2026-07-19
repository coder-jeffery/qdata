"""个股研判：P0 打分/强弱；P1 因子画像/可交易性；P2 规则简报。

P0 分数 0–100（越高越偏多/健康）：
  momentum / volatility(反向) / valuation(ep) / turnover(反向) / quality(bp)

P1：
  - 因子画像：六种子因子全市场分位 + 行业内分位
  - 事件与可交易性：近端涨跌停/停牌/ST/财务公告滞后

P2：
  - 固定模板中文简报（基于卡片字段，非 LLM）
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qdata import db
from qdata.api.data_api import DataAPI
from qdata.factors import list_seed_factors

DIMENSIONS = ("momentum", "volatility", "valuation", "turnover", "quality")

# 因子 → 维度；invert=True 表示因子越大分数越低
_DIM_FACTORS: dict[str, tuple[str, bool]] = {
    "momentum": ("mom_20", False),
    "volatility": ("vol_20", True),
    "valuation": ("ep", False),
    "turnover": ("turn_20", True),
    "quality": ("bp", False),
}


@dataclass
class JudgmentCard:
    code: str
    asof: str
    benchmark: str
    window: int
    scores: dict[str, float | None] = field(default_factory=dict)
    percentiles: dict[str, float | None] = field(default_factory=dict)
    raw_factors: dict[str, float | None] = field(default_factory=dict)
    composite: float | None = None
    stance: str = "unknown"  # 偏强 | 中性 | 偏弱 | unknown
    relative_strength: float | None = None
    stock_return: float | None = None
    bench_return: float | None = None
    tags: list[str] = field(default_factory=list)
    industry: dict[str, str] = field(default_factory=dict)
    # P1
    factor_profile: list[dict[str, Any]] = field(default_factory=list)
    tradability: dict[str, Any] = field(default_factory=dict)
    # P2
    brief: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def judge_stock(
    code: str,
    asof: dt.date | None = None,
    *,
    benchmark: str = "000905.SH",
    window: int = 20,
    universe: str = "ALL",
    industry_level: str = "sw_l1",
    event_lookback: int = 20,
    include_p1: bool = True,
    include_brief: bool = True,
) -> JudgmentCard:
    """生成个股研判卡片（默认含 P1 + P2 简报）。"""
    code = code.strip().upper()
    if asof is None:
        asof = _latest_bar_date()
    if asof is None:
        return JudgmentCard(
            code=code,
            asof="",
            benchmark=benchmark,
            window=window,
            tags=["无行情数据"],
            stance="unknown",
            tradability={"status": "blocked", "tradeable": False, "notes": ["无行情"]},
        )

    api = DataAPI(allow_unpublished=True)
    industry = {}
    for lv in ("sw_l1", "sw_l2"):
        try:
            s = api.get_industry([code], asof, level=lv)  # type: ignore[arg-type]
            industry[lv] = str(s.get(code, "")) if not s.empty else ""
        except Exception:
            industry[lv] = ""

    raw, pct = _factor_snapshot(code, asof, universe=universe)
    scores: dict[str, float | None] = {}
    percentiles: dict[str, float | None] = {}
    for dim, (fac, invert) in _DIM_FACTORS.items():
        p = pct.get(fac)
        percentiles[dim] = p
        if p is None:
            scores[dim] = None
        else:
            scores[dim] = float(100.0 * (1.0 - p) if invert else 100.0 * p)

    present = [scores[d] for d in DIMENSIONS if scores.get(d) is not None]
    composite = float(np.mean(present)) if present else None

    stock_ret, bench_ret, rs = _relative_strength(
        code, asof, benchmark=benchmark, window=window
    )
    tags = _build_tags(code, asof, scores, rs, raw)

    profile: list[dict[str, Any]] = []
    tradability: dict[str, Any] = {}
    if include_p1:
        profile = build_factor_profile(
            code, asof, industry=industry.get(industry_level, ""), level=industry_level
        )
        tradability = build_tradability(code, asof, lookback=event_lookback)
        tags = _merge_p1_tags(tags, profile, tradability)

    stance = _stance(composite, rs, tradability)

    card = JudgmentCard(
        code=code,
        asof=asof.isoformat(),
        benchmark=benchmark,
        window=window,
        scores=scores,
        percentiles=percentiles,
        raw_factors=raw,
        composite=composite,
        stance=stance,
        relative_strength=rs,
        stock_return=stock_ret,
        bench_return=bench_ret,
        tags=tags,
        industry=industry,
        factor_profile=profile,
        tradability=tradability,
        meta={
            "universe": universe,
            "n_scored": len(present),
            "factor_map": {k: v[0] for k, v in _DIM_FACTORS.items()},
            "industry_level": industry_level,
            "event_lookback": event_lookback,
            "include_p1": include_p1,
            "include_brief": include_brief,
        },
    )
    if include_brief:
        card.brief = build_brief(card)
    return card


_DIM_CN = {
    "momentum": "动量",
    "volatility": "波动控制",
    "valuation": "估值",
    "turnover": "拥挤度",
    "quality": "质量",
}


def build_brief(card: JudgmentCard) -> dict[str, Any]:
    """基于卡片字段生成固定模板中文简报（非 LLM）。"""
    ind = card.industry.get("sw_l1") or "未知行业"
    if "|" in ind:
        ind_name = ind.split("|", 1)[1]
    else:
        ind_name = ind

    comp = card.composite
    comp_s = f"{comp:.1f}" if comp is not None else "—"
    rs = card.relative_strength
    rs_s = f"{rs:+.2%}" if rs is not None else "—"
    stock_s = f"{card.stock_return:+.2%}" if card.stock_return is not None else "—"
    bench_s = f"{card.bench_return:+.2%}" if card.bench_return is not None else "—"

    headline = (
        f"{card.code}（{ind_name}）@{card.asof}：立场【{card.stance}】，"
        f"综合分 {comp_s}，相对 {card.benchmark} {card.window} 日强弱 {rs_s}"
    )

    # 维度解读
    dim_bits: list[str] = []
    for dim in DIMENSIONS:
        sc = card.scores.get(dim)
        if sc is None:
            continue
        label = _DIM_CN.get(dim, dim)
        if sc >= 70:
            tone = "偏强"
        elif sc <= 30:
            tone = "偏弱"
        else:
            tone = "中性"
        dim_bits.append(f"{label}{tone}（{sc:.0f}）")
    score_para = "五维概况：" + ("；".join(dim_bits) if dim_bits else "因子不足，暂无完整打分。")

    # 相对强弱
    if rs is None:
        rs_para = "相对强弱：基准收益不可用或样本不足，暂无法比较。"
    elif rs >= 0.03:
        rs_para = (
            f"相对强弱：近 {card.window} 日个股 {stock_s}、基准 {bench_s}，"
            f"超额 {rs_s}，显著跑赢。"
        )
    elif rs <= -0.03:
        rs_para = (
            f"相对强弱：近 {card.window} 日个股 {stock_s}、基准 {bench_s}，"
            f"超额 {rs_s}，显著跑输。"
        )
    else:
        rs_para = (
            f"相对强弱：近 {card.window} 日个股 {stock_s}、基准 {bench_s}，"
            f"超额 {rs_s}，与基准大致相当。"
        )

    # 行业内画像要点
    profile_bits: list[str] = []
    for row in card.factor_profile or []:
        fac = row.get("factor")
        pi = row.get("pct_industry")
        pm = row.get("pct_market")
        if fac == "mom_20" and pi is not None:
            profile_bits.append(f"行业内动量分位 {pi:.0%}（全市场 {_pct(pm)}）")
        if fac == "ep" and pi is not None:
            profile_bits.append(f"行业内 EP 分位 {pi:.0%}")
        if fac == "bp" and pi is not None:
            profile_bits.append(f"行业内 BP 分位 {pi:.0%}")
    profile_para = (
        "因子画像：" + "；".join(profile_bits) + "。"
        if profile_bits
        else "因子画像：未计算（可用 include_p1）。"
    )

    # 可交易性
    tb = card.tradability or {}
    status = tb.get("status", "—")
    notes = tb.get("notes") or []
    if status == "blocked":
        trade_para = "可交易性：当前不可交易（" + "；".join(notes or ["受限"]) + "）。"
    elif status == "caution":
        trade_para = "可交易性：谨慎（" + "；".join(notes) + "）。" if notes else "可交易性：谨慎。"
    elif status == "ok":
        trade_para = (
            f"可交易性：正常；近 {tb.get('lookback_days', '—')} 日"
            f"涨停 {tb.get('n_limit_up', 0)} / 跌停 {tb.get('n_limit_down', 0)} / "
            f"停牌 {tb.get('n_suspended', 0)}。"
        )
    else:
        trade_para = "可交易性：未评估。"

    # 结论与风险
    risks = [t for t in (card.tags or []) if t in (
        "停牌", "ST", "涨停", "跌停", "换手拥挤", "波动偏高",
        "财务数据陈旧", "不可交易", "交易谨慎", "因子不全",
        "行业动量垫底",
    )]
    if card.stance == "偏强" and status != "blocked":
        conclusion = "结论：多维信号偏积极，可作为观察/加权利候选，但仍需结合基本面与流动性自行裁决。"
    elif card.stance == "偏弱" or status == "blocked":
        conclusion = "结论：信号偏谨慎或交易受限，不宜作为进攻仓位首选。"
    else:
        conclusion = "结论：多空信号混杂，建议观望或轻仓跟踪，等待相对强弱与可交易性改善。"
    if risks:
        conclusion += " 主要风险提示：" + "、".join(risks) + "。"
    conclusion += "（规则简报，非投资建议，非收益预测。）"

    paragraphs = [score_para, rs_para, profile_para, trade_para, conclusion]
    bullets = [
        f"立场：{card.stance}｜综合分 {comp_s}",
        f"强弱：{rs_s}（个股 {stock_s} / 基准 {bench_s}）",
        f"行业：{ind_name}",
        f"可交易：{status}",
    ]
    if card.tags:
        bullets.append("标签：" + "、".join(card.tags[:8]))

    markdown = "\n".join(
        [
            f"# 个股研判简报 · {card.code}",
            "",
            f"**{headline}**",
            "",
            *[f"- {b}" for b in bullets],
            "",
            "## 详述",
            "",
            *[f"{i}. {p}" for i, p in enumerate(paragraphs, 1)],
            "",
            f"_生成规则：qdata.research.judgment / asof={card.asof}_",
        ]
    )

    return {
        "headline": headline,
        "bullets": bullets,
        "paragraphs": paragraphs,
        "markdown": markdown,
        "disclaimer": "规则简报，非投资建议，非收益预测。",
    }


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{float(v):.0%}"


def build_factor_profile(
    code: str,
    asof: dt.date,
    *,
    industry: str = "",
    level: str = "sw_l1",
) -> list[dict[str, Any]]:
    """六因子：全市场分位 + 同行业分位。"""
    code = code.strip().upper()
    factors = list_seed_factors()
    own = db.query_df(
        """
        SELECT f.factor_name, f.value
        FROM factor_value f
        INNER JOIN security_master m USING (security_id)
        WHERE m.exchange_code = %(c)s
          AND f.trade_date = %(d)s
          AND f.factor_name IN %(fs)s
          AND isFinite(f.value) AND NOT isNaN(f.value)
        """,
        {"c": code, "d": asof, "fs": tuple(factors)},
    )
    raw: dict[str, float] = {}
    if own is not None and not own.empty:
        for _, r in own.iterrows():
            raw[str(r["factor_name"])] = float(r["value"])

    market = db.query_df(
        """
        SELECT f.factor_name, f.value
        FROM factor_value f
        WHERE f.trade_date = %(d)s
          AND f.factor_name IN %(fs)s
          AND isFinite(f.value) AND NOT isNaN(f.value)
        """,
        {"d": asof, "fs": tuple(factors)},
    )
    industry_cross = pd.DataFrame()
    if industry:
        industry_cross = db.query_df(
            """
            SELECT f.factor_name, f.value
            FROM factor_value f
            INNER JOIN industry_member im ON im.security_id = f.security_id
            WHERE f.trade_date = %(d)s
              AND f.factor_name IN %(fs)s
              AND im.level = %(lv)s
              AND im.industry = %(ind)s
              AND im.in_date <= %(d)s AND im.out_date > %(d)s
              AND isFinite(f.value) AND NOT isNaN(f.value)
            """,
            {
                "d": asof,
                "fs": tuple(factors),
                "lv": level,
                "ind": industry,
            },
        )

    rows: list[dict[str, Any]] = []
    for fac in factors:
        v = raw.get(fac)
        m_series = (
            pd.to_numeric(
                market.loc[market["factor_name"] == fac, "value"], errors="coerce"
            ).dropna()
            if market is not None and not market.empty
            else pd.Series(dtype=float)
        )
        i_series = (
            pd.to_numeric(
                industry_cross.loc[industry_cross["factor_name"] == fac, "value"],
                errors="coerce",
            ).dropna()
            if industry_cross is not None and not industry_cross.empty
            else pd.Series(dtype=float)
        )
        pct_m = float((m_series <= v).mean()) if v is not None and len(m_series) else None
        pct_i = float((i_series <= v).mean()) if v is not None and len(i_series) else None
        rows.append(
            {
                "factor": fac,
                "value": v,
                "pct_market": pct_m,
                "pct_industry": pct_i,
                "n_market": int(len(m_series)),
                "n_industry": int(len(i_series)),
                "industry": industry,
            }
        )
    return rows


def build_tradability(
    code: str,
    asof: dt.date,
    *,
    lookback: int = 20,
) -> dict[str, Any]:
    """近端事件与可交易性。"""
    code = code.strip().upper()
    bars = db.query_df(
        """
        SELECT b.trade_date, b.close, b.up_limit, b.down_limit,
               b.is_suspended, b.is_st
        FROM daily_bar b
        INNER JOIN security_master m USING (security_id)
        WHERE m.exchange_code = %(c)s
          AND b.trade_date <= %(d)s
        ORDER BY b.trade_date DESC
        LIMIT %(n)s
        """,
        {"c": code, "d": asof, "n": int(lookback)},
    )
    events: list[dict[str, Any]] = []
    n_up = n_down = n_sus = 0
    is_st = False
    if bars is not None and not bars.empty:
        for _, r in bars.iterrows():
            close = float(r["close"] or 0)
            up, down = r.get("up_limit"), r.get("down_limit")
            sus = int(r.get("is_suspended") or 0) == 1
            st = int(r.get("is_st") or 0) == 1
            if st:
                is_st = True
            if sus:
                n_sus += 1
                events.append(
                    {
                        "trade_date": str(pd.Timestamp(r["trade_date"]).date()),
                        "event": "suspended",
                    }
                )
            if (
                up is not None
                and pd.notna(up)
                and close > 0
                and abs(close - float(up)) < 1e-6
            ):
                n_up += 1
                events.append(
                    {
                        "trade_date": str(pd.Timestamp(r["trade_date"]).date()),
                        "event": "limit_up",
                    }
                )
            if (
                down is not None
                and pd.notna(down)
                and close > 0
                and abs(close - float(down)) < 1e-6
            ):
                n_down += 1
                events.append(
                    {
                        "trade_date": str(pd.Timestamp(r["trade_date"]).date()),
                        "event": "limit_down",
                    }
                )

    # suspend 表补充
    sus_tbl = db.query_df(
        """
        SELECT s.suspend_date, s.resume_date
        FROM suspend s
        INNER JOIN security_master m USING (security_id)
        WHERE m.exchange_code = %(c)s
          AND s.suspend_date <= %(d)s
        ORDER BY s.suspend_date DESC
        LIMIT 5
        """,
        {"c": code, "d": asof},
    )
    last_suspend = ""
    if sus_tbl is not None and not sus_tbl.empty:
        last_suspend = str(pd.Timestamp(sus_tbl.iloc[0]["suspend_date"]).date())

    # 个股财务公告滞后
    fin = db.query_df(
        """
        SELECT max(f.ann_date) AS mx
        FROM fin_statement f
        INNER JOIN security_master m USING (security_id)
        WHERE m.exchange_code = %(c)s AND f.ann_date <= %(d)s
        """,
        {"c": code, "d": asof},
    )
    fin_ann = ""
    fin_lag: int | None = None
    if fin is not None and not fin.empty and pd.notna(fin.iloc[0]["mx"]):
        fin_ann_d = pd.Timestamp(fin.iloc[0]["mx"]).date()
        fin_ann = fin_ann_d.isoformat()
        fin_lag = (asof - fin_ann_d).days

    notes: list[str] = []
    status = "ok"
    tradeable = True
    asof_bar = None
    if bars is not None and not bars.empty:
        asof_bar = bars.iloc[0]
        if int(asof_bar.get("is_suspended") or 0) == 1:
            status, tradeable = "blocked", False
            notes.append("当日停牌")
        close = float(asof_bar.get("close") or 0)
        up, down = asof_bar.get("up_limit"), asof_bar.get("down_limit")
        if up is not None and pd.notna(up) and close > 0 and abs(close - float(up)) < 1e-6:
            status = "caution" if tradeable else status
            notes.append("当日涨停（买入困难）")
        if down is not None and pd.notna(down) and close > 0 and abs(close - float(down)) < 1e-6:
            status = "caution" if tradeable else status
            notes.append("当日跌停（卖出困难）")
    else:
        status, tradeable = "blocked", False
        notes.append("无当日行情")

    if is_st:
        if status == "ok":
            status = "caution"
        notes.append("ST")
    if n_sus >= 3:
        if status == "ok":
            status = "caution"
        notes.append(f"近{lookback}日停牌{n_sus}次")
    if n_up + n_down >= 3:
        if status == "ok":
            status = "caution"
        notes.append(f"近{lookback}日涨跌停{(n_up + n_down)}次")
    if fin_lag is not None and fin_lag > 90:
        if status == "ok":
            status = "caution"
        notes.append(f"个股财务公告滞后{fin_lag}日")
    elif fin_lag is None:
        notes.append("无个股财务公告记录")

    return {
        "tradeable": tradeable,
        "status": status,  # ok | caution | blocked
        "lookback_days": lookback,
        "n_limit_up": n_up,
        "n_limit_down": n_down,
        "n_suspended": n_sus,
        "is_st": is_st,
        "last_suspend_date": last_suspend,
        "finance_ann_date": fin_ann,
        "finance_ann_lag_days": fin_lag,
        "events": events[:30],
        "notes": notes,
    }


def _latest_bar_date() -> dt.date | None:
    df = db.query_df("SELECT max(trade_date) AS mx FROM daily_bar")
    if df is None or df.empty or pd.isna(df.iloc[0]["mx"]):
        return None
    return pd.Timestamp(df.iloc[0]["mx"]).date()


def _factor_snapshot(
    code: str,
    asof: dt.date,
    *,
    universe: str = "ALL",
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """返回 raw 因子值 + 全市场（或指数内）百分位 [0,1]。"""
    factors = [fac for fac, _ in _DIM_FACTORS.values()]
    raw: dict[str, float | None] = {f: None for f in factors}
    pct: dict[str, float | None] = {f: None for f in factors}

    own = db.query_df(
        """
        SELECT f.factor_name, f.value
        FROM factor_value f
        INNER JOIN security_master m USING (security_id)
        WHERE m.exchange_code = %(c)s
          AND f.trade_date = %(d)s
          AND f.factor_name IN %(fs)s
          AND isFinite(f.value) AND NOT isNaN(f.value)
        """,
        {"c": code, "d": asof, "fs": tuple(factors)},
    )
    if own is not None and not own.empty:
        for _, r in own.iterrows():
            raw[str(r["factor_name"])] = float(r["value"])

    if universe in ("ALL", "*", "all", ""):
        cross = db.query_df(
            """
            SELECT f.factor_name, f.value
            FROM factor_value f
            WHERE f.trade_date = %(d)s
              AND f.factor_name IN %(fs)s
              AND isFinite(f.value) AND NOT isNaN(f.value)
            """,
            {"d": asof, "fs": tuple(factors)},
        )
    else:
        cross = db.query_df(
            """
            SELECT f.factor_name, f.value
            FROM factor_value f
            INNER JOIN index_member im ON im.security_id = f.security_id
            WHERE f.trade_date = %(d)s
              AND f.factor_name IN %(fs)s
              AND im.index_code = %(idx)s
              AND im.in_date <= %(d)s AND im.out_date > %(d)s
              AND isFinite(f.value) AND NOT isNaN(f.value)
            """,
            {"d": asof, "fs": tuple(factors), "idx": universe},
        )
    if cross is None or cross.empty:
        return raw, pct

    for fac in factors:
        v = raw.get(fac)
        if v is None:
            continue
        series = pd.to_numeric(
            cross.loc[cross["factor_name"] == fac, "value"], errors="coerce"
        ).dropna()
        if series.empty:
            continue
        pct[fac] = float((series <= v).mean())
    return raw, pct


def _relative_strength(
    code: str,
    asof: dt.date,
    *,
    benchmark: str,
    window: int,
) -> tuple[float | None, float | None, float | None]:
    days = db.query_df(
        """
        SELECT trade_date
        FROM daily_bar
        WHERE trade_date <= %(d)s
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT %(n)s
        """,
        {"d": asof, "n": int(window) + 1},
    )
    if days is None or len(days) < 2:
        return None, None, None
    dates = sorted(pd.to_datetime(days["trade_date"]).dt.date.tolist())
    start, end = dates[0], dates[-1]

    api = DataAPI(allow_unpublished=True)
    px = api.get_price([code], start, end, adjust="post")
    if px is None or px.empty or len(px) < 2:
        return None, None, None
    px = px.sort_values("trade_date")
    c0, c1 = float(px.iloc[0]["close"]), float(px.iloc[-1]["close"])
    if c0 <= 0:
        return None, None, None
    stock_ret = c1 / c0 - 1.0

    mem = db.query_df(
        """
        SELECT m.exchange_code
        FROM index_member im
        INNER JOIN security_master m ON m.security_id = im.security_id
        WHERE im.index_code = %(idx)s
          AND im.in_date <= %(d)s AND im.out_date > %(d)s
        """,
        {"idx": benchmark, "d": asof},
    )
    if mem is None or mem.empty:
        return stock_ret, None, None
    codes = mem["exchange_code"].astype(str).tolist()
    if len(codes) > 200:
        codes = codes[:: max(1, len(codes) // 200)][:200]
    bpx = api.get_price(codes, start, end, adjust="post")
    if bpx is None or bpx.empty:
        return stock_ret, None, None
    wide = bpx.pivot_table(index="trade_date", columns="exchange_code", values="close")
    wide = wide.sort_index()
    if len(wide) < 2:
        return stock_ret, None, None
    rets = wide.iloc[-1] / wide.iloc[0] - 1.0
    bench_ret = float(rets.dropna().mean()) if not rets.dropna().empty else None
    if bench_ret is None:
        return stock_ret, None, None
    return stock_ret, bench_ret, float(stock_ret - bench_ret)


def _build_tags(
    code: str,
    asof: dt.date,
    scores: dict[str, float | None],
    rs: float | None,
    raw: dict[str, float | None],
) -> list[str]:
    tags: list[str] = []
    bar = db.query_df(
        """
        SELECT b.close, b.up_limit, b.down_limit, b.is_suspended, b.is_st
        FROM daily_bar b
        INNER JOIN security_master m USING (security_id)
        WHERE m.exchange_code = %(c)s AND b.trade_date = %(d)s
        LIMIT 1
        """,
        {"c": code, "d": asof},
    )
    if bar is not None and not bar.empty:
        r = bar.iloc[0]
        if int(r.get("is_suspended") or 0) == 1:
            tags.append("停牌")
        if int(r.get("is_st") or 0) == 1:
            tags.append("ST")
        close = float(r.get("close") or 0)
        up = r.get("up_limit")
        down = r.get("down_limit")
        if up is not None and pd.notna(up) and close > 0 and abs(close - float(up)) < 1e-6:
            tags.append("涨停")
        if down is not None and pd.notna(down) and close > 0 and abs(close - float(down)) < 1e-6:
            tags.append("跌停")

    mom = scores.get("momentum")
    if mom is not None:
        if mom >= 70:
            tags.append("动量偏强")
        elif mom <= 30:
            tags.append("动量偏弱")
    vol = scores.get("volatility")
    if vol is not None and vol <= 30:
        tags.append("波动偏高")
    val = scores.get("valuation")
    if val is not None and val <= 30:
        tags.append("估值偏贵")
    elif val is not None and val >= 70:
        tags.append("估值偏便宜")
    turn = scores.get("turnover")
    if turn is not None and turn <= 30:
        tags.append("换手拥挤")
    if rs is not None:
        if rs >= 0.03:
            tags.append("跑赢基准")
        elif rs <= -0.03:
            tags.append("跑输基准")

    if any(v is None for v in raw.values()):
        tags.append("因子不全")

    fin = db.query_df("SELECT max(ann_date) AS mx FROM fin_statement")
    if fin is not None and not fin.empty and pd.notna(fin.iloc[0]["mx"]):
        fin_max = pd.Timestamp(fin.iloc[0]["mx"]).date()
        if (asof - fin_max).days > 30:
            tags.append("财务数据陈旧")

    return tags


def _merge_p1_tags(
    tags: list[str],
    profile: list[dict[str, Any]],
    tradability: dict[str, Any],
) -> list[str]:
    out = list(tags)
    # 行业内极端分位
    for row in profile:
        fac = row.get("factor")
        pi = row.get("pct_industry")
        if pi is None:
            continue
        if fac == "mom_20" and pi >= 0.9 and "行业动量顶尖" not in out:
            out.append("行业动量顶尖")
        if fac == "mom_20" and pi <= 0.1 and "行业动量垫底" not in out:
            out.append("行业动量垫底")
        if fac in ("ep", "bp") and pi >= 0.9 and "行业价值顶尖" not in out:
            out.append("行业价值顶尖")
    status = tradability.get("status")
    if status == "blocked" and "不可交易" not in out:
        out.append("不可交易")
    elif status == "caution" and "交易谨慎" not in out:
        out.append("交易谨慎")
    return out


def judge_stocks(
    codes: list[str],
    asof: dt.date | None = None,
    *,
    benchmark: str = "000905.SH",
    window: int = 20,
    universe: str = "ALL",
    industry_level: str = "sw_l1",
    event_lookback: int = 20,
    include_p1: bool = True,
    include_brief: bool = False,
    continue_on_error: bool = True,
) -> list[JudgmentCard]:
    """批量研判（A207）；默认不生成简报以提速。"""
    out: list[JudgmentCard] = []
    for code in codes:
        c = str(code).strip().upper()
        if not c:
            continue
        try:
            out.append(
                judge_stock(
                    c,
                    asof,
                    benchmark=benchmark,
                    window=window,
                    universe=universe,
                    industry_level=industry_level,
                    event_lookback=event_lookback,
                    include_p1=include_p1,
                    include_brief=include_brief,
                )
            )
        except Exception as e:
            if not continue_on_error:
                raise
            out.append(
                JudgmentCard(
                    code=c,
                    asof=asof.isoformat() if asof else "",
                    benchmark=benchmark,
                    window=window,
                    stance="unknown",
                    tags=["error"],
                    meta={"error": str(e)},
                )
            )
    return out


def judgments_to_frame(cards: list[JudgmentCard]) -> pd.DataFrame:
    """批量研判结果 → 摘要表。"""
    rows: list[dict[str, Any]] = []
    for c in cards:
        tb = c.tradability or {}
        rows.append(
            {
                "exchange_code": c.code,
                "asof": c.asof,
                "stance": c.stance,
                "composite": c.composite,
                "relative_strength": c.relative_strength,
                "tradability": tb.get("status"),
                "sw_l1": (c.industry or {}).get("sw_l1"),
                "tags": ",".join(c.tags or []),
                "error": (c.meta or {}).get("error"),
            }
        )
    return pd.DataFrame(rows)


def judge_signal_topn(
    signal_dir: str | Path | None = None,
    *,
    weights: pd.DataFrame | None = None,
    asof: dt.date | None = None,
    top_n: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """A207：信号权重 TopN → 批量研判。"""
    meta: dict[str, Any] = {}
    if weights is None:
        if signal_dir is None:
            raise ValueError("需 signal_dir 或 weights")
        from qdata.apps.signal import load_signal

        data = load_signal(signal_dir)
        weights = data["weights"]
        meta = data.get("meta") or {}
        if asof is None and meta.get("asof"):
            asof = dt.date.fromisoformat(str(meta["asof"]))
    if weights is None or weights.empty:
        return {"cards": [], "summary": pd.DataFrame(), "meta": meta, "n": 0}

    w = weights.copy()
    if "weight" in w.columns:
        w = w.sort_values("weight", ascending=False)
    if top_n is not None:
        w = w.head(int(top_n))
    codes = w["exchange_code"].astype(str).tolist()
    cards = judge_stocks(codes, asof, **kwargs)
    return {
        "cards": cards,
        "summary": judgments_to_frame(cards),
        "codes": codes,
        "meta": meta,
        "n": len(cards),
        "signal_dir": str(signal_dir) if signal_dir else None,
    }


def _stance(
    composite: float | None,
    rs: float | None,
    tradability: dict[str, Any] | None = None,
) -> str:
    if tradability and tradability.get("status") == "blocked":
        return "偏弱"
    if composite is None and rs is None:
        return "unknown"
    score = composite if composite is not None else 50.0
    adj = 0.0
    if rs is not None:
        adj = float(np.clip(rs * 100.0, -10.0, 10.0))
    x = score + adj
    if x >= 58:
        return "偏强"
    if x <= 42:
        return "偏弱"
    return "中性"
