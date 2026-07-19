"""个股研判 CLI（P0+P1+P2）+ A207 批量/信号联动。

用法：
  python -m qdata.jobs.stock_judgment --code 600000.SH
  python -m qdata.jobs.stock_judgment --code 600000.SH --brief-only
  python -m qdata.jobs.stock_judgment --codes 600000.SH,000001.SZ --date 2026-07-15
  python -m qdata.jobs.stock_judgment --signal data/data-lake/signals/2026-07-15/.../ --top-n 10
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from qdata.research.judgment import (
    judge_signal_topn,
    judge_stock,
    judge_stocks,
    judgments_to_frame,
)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="个股研判卡片（P0+P1+P2 简报）/ A207 批量")
    p.add_argument("--code", default=None, help="单票，如 600000.SH")
    p.add_argument("--codes", default=None, help="批量，逗号分隔")
    p.add_argument("--signal", default=None, help="A207：信号目录 → TopN 批量研判")
    p.add_argument("--top-n", type=int, default=None, help="信号 TopN（默认全部权重）")
    p.add_argument("--date", default=None, help="as-of YYYY-MM-DD，默认最新日线日")
    p.add_argument("--benchmark", default="000905.SH")
    p.add_argument("--window", type=int, default=20)
    p.add_argument("--universe", default="ALL", help="分位宇宙 ALL|指数代码")
    p.add_argument("--industry-level", default="sw_l1", choices=("sw_l1", "sw_l2"))
    p.add_argument("--event-lookback", type=int, default=20)
    p.add_argument("--no-p1", action="store_true", help="跳过画像/可交易性")
    p.add_argument("--no-brief", action="store_true", help="不生成简报")
    p.add_argument("--brief-only", action="store_true", help="只打印简报正文（单票）")
    p.add_argument("--write-brief", default=None, help="将 Markdown 简报写入文件（单票）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    args = p.parse_args(argv)

    asof = dt.date.fromisoformat(args.date) if args.date else None
    common = dict(
        benchmark=args.benchmark,
        window=args.window,
        universe=args.universe,
        industry_level=args.industry_level,
        event_lookback=args.event_lookback,
        include_p1=not args.no_p1,
    )

    # —— A207 信号 / 批量 ——
    if args.signal or args.codes:
        if args.signal:
            result = judge_signal_topn(
                args.signal,
                asof=asof,
                top_n=args.top_n,
                include_brief=False,
                **common,
            )
            summary = result["summary"]
            print(f"JUDGMENT_SIGNAL n={result['n']} asof={asof or result.get('meta', {}).get('asof')}")
        else:
            codes = [x.strip() for x in args.codes.split(",") if x.strip()]
            cards = judge_stocks(codes, asof, include_brief=False, **common)
            summary = judgments_to_frame(cards)
            print(f"JUDGMENT_BATCH n={len(cards)}")

        if args.json:
            print(summary.to_json(orient="records", force_ascii=False, indent=2))
        else:
            print(summary.to_string(index=False))
        sys.exit(0)

    if not args.code:
        raise SystemExit("需 --code、--codes 或 --signal")

    card = judge_stock(
        args.code,
        asof,
        include_brief=not args.no_brief or bool(args.write_brief) or args.brief_only,
        **common,
    )

    if args.write_brief:
        path = Path(args.write_brief)
        path.parent.mkdir(parents=True, exist_ok=True)
        md = (card.brief or {}).get("markdown") or ""
        path.write_text(md, encoding="utf-8")
        print(f"brief written → {path}")

    if args.json:
        print(json.dumps(card.to_dict(), ensure_ascii=False, indent=2, default=str))
        sys.exit(0 if card.stance != "unknown" or card.composite is not None else 2)

    if args.brief_only:
        brief = card.brief or {}
        print(brief.get("markdown") or brief.get("headline") or "(无简报)")
        sys.exit(0)

    tb = card.tradability or {}
    print(
        f"JUDGMENT {card.code} @{card.asof} stance={card.stance} "
        f"composite={card.composite} tradability={tb.get('status', '—')}"
    )
    print(
        f"  RS({card.window}d vs {card.benchmark})={card.relative_strength} "
        f"stock={card.stock_return} bench={card.bench_return}"
    )
    print(f"  industry L1={card.industry.get('sw_l1')}")
    print(f"  scores={card.scores}")
    print(f"  tags={card.tags}")
    if card.factor_profile:
        print("  factor_profile:")
        for row in card.factor_profile:
            print(
                f"    {row.get('factor_name')}: pct={row.get('pct_universe')} "
                f"ind={row.get('pct_industry')}"
            )
    if card.brief:
        print(f"  brief: {(card.brief or {}).get('headline', '')}")
    sys.exit(0)


if __name__ == "__main__":
    main()
