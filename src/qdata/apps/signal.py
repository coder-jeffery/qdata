"""A2 研究信号台：asof 目标权重快照 + 暴露 / 可交易性预览。"""

from __future__ import annotations

import datetime as dt
import json
import logging
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from qdata.api.data_api import DataAPI
from qdata.config import settings
from qdata.research.portfolio import RebalanceSpec, day_panel, target_weights

logger = logging.getLogger(__name__)

IndustryLevel = Literal["sw_l1", "sw_l2"]
WeightMethod = Literal["equal", "factor_rank", "industry_neutral"]


def _signals_root() -> Path:
    return settings().lake_root / "signals"


def _signal_id(
    asof: dt.date,
    *,
    universe: str,
    factor: str,
    top_n: int,
    weight_method: str,
    version: str,
    industry_level: str,
    factor_version: str,
) -> str:
    payload = {
        "asof": asof.isoformat(),
        "universe": universe,
        "factor": factor,
        "top_n": top_n,
        "weight_method": weight_method,
        "version": version,
        "industry_level": industry_level,
        "factor_version": factor_version,
    }
    h = sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
    return f"{factor}_{weight_method}_{h}"


def _tradability_preview(codes: list[str], asof: dt.date) -> pd.DataFrame:
    """软预览：停牌 / 涨跌停（基于 asof 日 daily_bar）。"""
    if not codes:
        return pd.DataFrame(columns=["exchange_code", "is_suspended", "at_up_limit", "at_down_limit", "tradable"])
    try:
        from qdata import db

        df = db.query_df(
            """
            SELECT m.exchange_code,
                   b.is_suspended,
                   b.close,
                   b.up_limit,
                   b.down_limit
            FROM daily_bar b
            INNER JOIN security_master m USING (security_id)
            WHERE b.trade_date = %(d)s
              AND m.exchange_code IN %(codes)s
            """,
            {"d": asof, "codes": tuple(codes)},
        )
    except Exception as e:
        logger.warning("tradability preview 查询失败: %s", e)
        return pd.DataFrame(columns=["exchange_code", "is_suspended", "at_up_limit", "at_down_limit", "tradable"])

    if df is None or df.empty:
        return pd.DataFrame(
            {"exchange_code": codes, "is_suspended": [None] * len(codes), "tradable": [None] * len(codes)}
        )

    close = pd.to_numeric(df["close"], errors="coerce")
    up = pd.to_numeric(df["up_limit"], errors="coerce")
    down = pd.to_numeric(df["down_limit"], errors="coerce")
    df["at_up_limit"] = (close >= up * (1 - 1e-4)).astype(int)
    df["at_down_limit"] = (close <= down * (1 + 1e-4)).astype(int)
    df["tradable"] = (
        (pd.to_numeric(df["is_suspended"], errors="coerce").fillna(0) == 0)
        & (df["at_up_limit"] == 0)
        & (df["at_down_limit"] == 0)
    ).astype(int)
    return df


def _industry_exposure(
    api: DataAPI,
    weights: pd.DataFrame,
    asof: dt.date,
    *,
    universe: str,
    industry_level: IndustryLevel,
) -> pd.DataFrame:
    """信号权重 vs 指数成分的行业分布。"""
    if weights.empty:
        return pd.DataFrame(columns=["industry", "signal_weight", "index_weight", "diff"])

    codes = weights["exchange_code"].astype(str).tolist()
    ind_map = api.get_industry(codes, asof, level=industry_level)
    if isinstance(ind_map, pd.Series):
        weights = weights.copy()
        weights["industry"] = weights["exchange_code"].map(ind_map).fillna("UNKNOWN")
    else:
        weights = weights.copy()
        weights["industry"] = weights["exchange_code"].map(
            lambda c: (ind_map or {}).get(c, "UNKNOWN")
        ).fillna("UNKNOWN")

    sig = weights.groupby("industry", as_index=False)["weight"].sum().rename(columns={"weight": "signal_weight"})

    idx_codes = api.get_universe(universe, asof)
    if not idx_codes:
        sig["index_weight"] = 0.0
        sig["diff"] = sig["signal_weight"]
        return sig

    idx_ind = api.get_industry(idx_codes, asof, level=industry_level)
    if isinstance(idx_ind, pd.Series):
        idx_df = pd.DataFrame({"exchange_code": idx_codes})
        idx_df["industry"] = idx_df["exchange_code"].map(idx_ind).fillna("UNKNOWN")
    else:
        idx_df = pd.DataFrame(
            {"exchange_code": idx_codes, "industry": [idx_ind.get(c, "UNKNOWN") for c in idx_codes]}
        )
    idx_df["industry"] = idx_df["industry"].fillna("UNKNOWN")
    n = max(len(idx_df), 1)
    idx_exp = idx_df.groupby("industry", as_index=False).size().rename(columns={"size": "n"})
    idx_exp["index_weight"] = idx_exp["n"] / n
    idx_exp = idx_exp[["industry", "index_weight"]]

    out = sig.merge(idx_exp, on="industry", how="outer").fillna(0.0)
    out["diff"] = out["signal_weight"] - out["index_weight"]
    return out.sort_values("signal_weight", ascending=False).reset_index(drop=True)


def build_signal(
    asof: dt.date,
    universe: str = "000905.SH",
    factor: str = "mom_20",
    top_n: int = 50,
    weight_method: WeightMethod = "equal",
    industry_level: IndustryLevel = "sw_l1",
    version: str | None = None,
    *,
    factor_version: str = "v1",
    persist: bool = True,
) -> dict[str, Any]:
    """构建信号日目标权重并落盘。"""
    api = DataAPI(version=version) if version else DataAPI()
    need_ind = weight_method == "industry_neutral"
    panel = day_panel(
        api,
        asof,
        universe=universe,
        factor=factor,
        factor_version=factor_version,
        with_industry=need_ind,
        industry_level=industry_level,
    )
    weights = target_weights(panel, method=weight_method, top_n=top_n)

    signal_id = _signal_id(
        asof,
        universe=universe,
        factor=factor,
        top_n=top_n,
        weight_method=weight_method,
        version=api.version,
        industry_level=industry_level,
        factor_version=factor_version,
    )

    trad = _tradability_preview(weights["exchange_code"].tolist(), asof) if not weights.empty else tradability_empty()
    exposure = _industry_exposure(
        api, weights, asof, universe=universe, industry_level=industry_level
    )

    non_tradable = []
    if not trad.empty and "tradable" in trad.columns:
        bad = trad[trad["tradable"] == 0]["exchange_code"].tolist()
        non_tradable = bad

    meta: dict[str, Any] = {
        "signal_id": signal_id,
        "asof": asof.isoformat(),
        "universe": universe,
        "factor": factor,
        "factor_version": factor_version,
        "top_n": top_n,
        "weight_method": weight_method,
        "industry_level": industry_level,
        "dataset_version": api.version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_names": len(weights),
        "weight_sum": float(weights["weight"].sum()) if not weights.empty else 0.0,
        "non_tradable_count": len(non_tradable),
        "non_tradable": non_tradable[:20],
    }

    out_dir = _signals_root() / asof.isoformat() / signal_id
    path: str | None = None
    if persist:
        out_dir.mkdir(parents=True, exist_ok=True)
        weights.to_parquet(out_dir / "weights.parquet", index=False)
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if not exposure.empty:
            exposure.to_parquet(out_dir / "exposure.parquet", index=False)
        if not trad.empty:
            trad.to_parquet(out_dir / "tradability.parquet", index=False)
        path = str(out_dir)

    return {
        "signal_id": signal_id,
        "asof": asof,
        "weights": weights,
        "exposure": exposure,
        "tradability": trad,
        "meta": meta,
        "path": path,
    }


def tradability_empty() -> pd.DataFrame:
    return pd.DataFrame(columns=["exchange_code", "is_suspended", "at_up_limit", "at_down_limit", "tradable"])


def list_signals(asof: dt.date | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """列出 Lake 信号（Dashboard 用）。"""
    root = _signals_root()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    date_dirs = sorted([p for p in root.iterdir() if p.is_dir()], reverse=True)
    if asof is not None:
        date_dirs = [root / asof.isoformat()] if (root / asof.isoformat()).is_dir() else []
    for dd in date_dirs:
        for sd in sorted(dd.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not sd.is_dir():
                continue
            mp = sd / "meta.json"
            if not mp.is_file():
                continue
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                meta = {"signal_id": sd.name, "asof": dd.name}
            meta["path"] = str(sd)
            out.append(meta)
            if len(out) >= limit:
                return out
    return out


def load_signal(signal_dir: str | Path) -> dict[str, Any]:
    """从目录加载信号。"""
    d = Path(signal_dir)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    weights = pd.read_parquet(d / "weights.parquet")
    exposure = pd.read_parquet(d / "exposure.parquet") if (d / "exposure.parquet").is_file() else pd.DataFrame()
    trad = pd.read_parquet(d / "tradability.parquet") if (d / "tradability.parquet").is_file() else pd.DataFrame()
    return {"meta": meta, "weights": weights, "exposure": exposure, "tradability": trad, "path": str(d)}
