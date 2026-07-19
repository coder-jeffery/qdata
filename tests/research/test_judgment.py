"""个股研判 P0/P1 单测。"""

from __future__ import annotations

import datetime as dt

from qdata.research.judgment import (
    DIMENSIONS,
    build_brief,
    build_factor_profile,
    build_tradability,
    judge_stock,
)


def test_judge_stock_smoke():
    card = judge_stock("600000.SH", dt.date(2026, 7, 15), window=10)
    assert card.code == "600000.SH"
    assert card.asof == "2026-07-15"
    assert card.stance in ("偏强", "中性", "偏弱", "unknown")
    if card.composite is not None:
        assert 0.0 <= card.composite <= 100.0
        for dim in DIMENSIONS:
            s = card.scores.get(dim)
            if s is not None:
                assert 0.0 <= s <= 100.0
    assert isinstance(card.tags, list)
    d = card.to_dict()
    assert "scores" in d
    assert "factor_profile" in d
    assert "tradability" in d


def test_factor_profile_p1():
    asof = dt.date(2026, 7, 15)
    card = judge_stock("600000.SH", asof, include_p1=True)
    assert card.factor_profile
    names = {r["factor"] for r in card.factor_profile}
    assert "mom_20" in names and "ep" in names and "bp" in names
    for row in card.factor_profile:
        if row["pct_market"] is not None:
            assert 0.0 <= row["pct_market"] <= 1.0
        if row["pct_industry"] is not None:
            assert 0.0 <= row["pct_industry"] <= 1.0
            assert row["n_industry"] > 0

    # 独立 API
    ind = card.industry.get("sw_l1", "")
    prof = build_factor_profile("600000.SH", asof, industry=ind, level="sw_l1")
    assert len(prof) >= 5


def test_tradability_p1():
    tb = build_tradability("600000.SH", dt.date(2026, 7, 15), lookback=10)
    assert tb["status"] in ("ok", "caution", "blocked")
    assert "n_limit_up" in tb
    assert "finance_ann_lag_days" in tb or tb.get("finance_ann_date") == ""
    assert isinstance(tb["notes"], list)
    assert isinstance(tb["events"], list)


def test_judge_stock_unknown_code():
    card = judge_stock("999999.SH", dt.date(2026, 7, 15))
    assert card.code == "999999.SH"
    assert card.stance in ("偏强", "中性", "偏弱", "unknown")


def test_p0_only_skips_profile():
    card = judge_stock(
        "600000.SH", dt.date(2026, 7, 15), include_p1=False, include_brief=True
    )
    assert card.factor_profile == []
    assert card.tradability == {}
    assert card.brief.get("headline")


def test_brief_p2():
    card = judge_stock("600000.SH", dt.date(2026, 7, 15), include_p1=True)
    brief = card.brief
    assert brief
    assert "headline" in brief and card.code in brief["headline"]
    assert brief.get("paragraphs")
    assert "非投资建议" in (brief.get("disclaimer") or "")
    assert "# 个股研判简报" in (brief.get("markdown") or "")
    # 独立调用
    again = build_brief(card)
    assert again["headline"] == brief["headline"]
