"""研究入口冒烟：校验主数据/日线已入库，并用 DataAPI 读一笔。

用法：
  python -m qdata.jobs.smoke --date 2026-07-15
  python -m qdata.jobs.smoke --date 2026-07-15 --code 600000.SH
  python -m qdata.jobs.smoke --start 2026-07-01 --end 2026-07-15 --prod
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from qdata import calendar, db
from qdata.api.data_api import DataAPI
from qdata.prod import prod_min_universe

logger = logging.getLogger(__name__)


def run_smoke(
    trade_date: dt.date,
    code: str = "600000.SH",
    *,
    require_published: bool = False,
    min_universe: int | None = None,
    check_m2: bool = False,
) -> int:
    """返回 0 成功，非 0 失败。

    check_m2=True 时对指数/行业/因子/读数层做 **软检查**（表空仅打印，不失败），
    有数据但语义错误（如权重和偏离）才记入 errors。
    """
    errors: list[str] = []
    min_uni = prod_min_universe() if min_universe is None and require_published else (
        min_universe if min_universe is not None else 1
    )

    master_n = int(
        db.query_df("SELECT count() AS n FROM security_master")["n"][0]
    )
    bar_n = int(
        db.query_df(
            "SELECT count() AS n FROM daily_bar WHERE trade_date = %(d)s",
            {"d": trade_date},
        )["n"][0]
    )
    print(f"security_master rows={master_n}")
    print(f"daily_bar@{trade_date} rows={bar_n}")
    if master_n <= 0:
        errors.append("security_master 为空，请先 load security_master")
    if bar_n <= 0:
        errors.append(f"daily_bar@{trade_date} 为空，请先 backfill/load daily_bar")

    ver = db.query_df(
        "SELECT version, row_count FROM dataset_version "
        "WHERE dataset='daily_bar' AND version=%(v)s",
        {"v": trade_date.isoformat()},
    )
    published = not ver.empty
    print(f"dataset_version daily_bar@{trade_date}: {'yes' if published else 'no'}")
    if require_published and not published:
        errors.append(f"未发布 dataset_version daily_bar@{trade_date}")

    api: DataAPI | None = None
    try:
        api = DataAPI(
            version=trade_date.isoformat() if published else None,
            allow_unpublished=not require_published,
        )
        print(f"DataAPI.version={api.version}")

        uni = api.get_universe("ALL", trade_date, filters=["suspended"])
        print(f"universe ALL (ex-suspended) size={len(uni)}")
        if not uni:
            errors.append("get_universe(ALL) 为空")
        elif len(uni) < min_uni:
            errors.append(
                f"universe size={len(uni)} < min_universe={min_uni}（疑似非全市场）"
            )

        use_code = code if code in uni else (uni[0] if uni else code)
        px = api.get_price([use_code], trade_date, trade_date, adjust="post")
        print(f"get_price {use_code} rows={len(px)}")
        if px.empty:
            errors.append(f"get_price({use_code}) 为空")
        else:
            print(px.head(1).to_string(index=False))

        try:
            fin_n = int(
                db.query_df(
                    "SELECT count() AS n FROM fin_statement WHERE ann_date = %(d)s",
                    {"d": trade_date},
                )["n"][0]
            )
            print(f"fin_statement@{trade_date} rows={fin_n}")
            if fin_n > 0 and uni:
                s = api.get_fundamental("revenue", uni[:5], trade_date)
                print(f"get_fundamental revenue sample={len(s)}")
        except Exception as e:
            logger.warning("财务冒烟跳过: %s", e)

        if check_m2 and api is not None:
            _smoke_m2_soft(api, trade_date, use_code, errors)

    except Exception as e:
        errors.append(f"DataAPI 失败: {e}")
        logger.exception("smoke failed")

    if errors:
        print("SMOKE FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("SMOKE OK")
    return 0


def _smoke_m2_soft(
    api: DataAPI,
    trade_date: dt.date,
    sample_code: str,
    errors: list[str],
) -> None:
    """M2 软门禁：无数据只提示；有数据则校验语义。"""
    # 指数成分
    try:
        idx_n = int(db.query_df("SELECT count() AS n FROM index_member")["n"][0])
    except Exception as e:
        print(f"m2 soft: index_member 不可用 ({e})")
        idx_n = 0
    if idx_n <= 0:
        print("m2 soft: index_member 空（可 sync_index_member）")
    else:
        for idx in ("000300.SH", "000905.SH", "000852.SH"):
            uni = api.get_universe(idx, trade_date, filters=["suspended"])
            print(f"m2 soft: get_universe({idx}) size={len(uni)}")
            if len(uni) == 0:
                errors.append(f"index_member 有数据但 get_universe({idx}) 为空 @{trade_date}")

    # 行业
    try:
        ind_n = int(
            db.query_df(
                "SELECT count() AS n FROM industry_member WHERE level='sw_l1'"
            )["n"][0]
        )
    except Exception as e:
        print(f"m2 soft: industry_member 不可用 ({e})")
        ind_n = 0
    if ind_n <= 0:
        print("m2 soft: industry_member 空（可 sync_industry_member --levels sw_l1）")
    else:
        s = api.get_industry([sample_code], trade_date, level="sw_l1")
        print(f"m2 soft: get_industry({sample_code})={s.to_dict() if not s.empty else '{}'}")
        if s.empty:
            # 抽样代码可能不在映射内，再抽一只有行情的
            uni_all = api.get_universe("ALL", trade_date)
            hit = False
            for c in uni_all[:20]:
                if not api.get_industry([c], trade_date, level="sw_l1").empty:
                    hit = True
                    break
            if not hit:
                errors.append("industry_member 有数据但 get_industry 抽样全空")

    # 因子 + 读数层
    try:
        fac_n = int(
            db.query_df(
                "SELECT count() AS n FROM factor_value "
                "WHERE factor_name='mom_20' AND trade_date=%(d)s",
                {"d": trade_date},
            )["n"][0]
        )
    except Exception as e:
        print(f"m2 soft: factor_value 不可用 ({e})")
        fac_n = 0
    if fac_n <= 0:
        print("m2 soft: mom_20 空（可 compute_factors）")
        return

    fac = api.load_factor("mom_20", trade_date, trade_date)
    print(f"m2 soft: load_factor mom_20 rows={len(fac)}")
    if fac.empty:
        errors.append("factor_value 有 mom_20 行但 load_factor 为空")
        return

    try:
        from qdata.research.portfolio import day_panel, target_weights

        panel = day_panel(api, trade_date, universe="ALL", factor="mom_20", filters=["suspended"])
        if panel.empty:
            print("m2 soft: day_panel 空（universe∩factor 无交集，跳过权重）")
            return
        w = target_weights(panel, method="equal", top_n=min(50, len(panel)))
        ssum = float(w["weight"].sum()) if not w.empty else 0.0
        print(f"m2 soft: target_weights rows={len(w)} sum={ssum:.6f}")
        if w.empty or abs(ssum - 1.0) > 1e-6:
            errors.append(f"target_weights 权重和异常: {ssum}")
    except Exception as e:
        logger.warning("m2 soft portfolio 跳过: %s", e)


def run_smoke_range(
    start: dt.date,
    end: dt.date,
    code: str = "600000.SH",
    *,
    require_published: bool = True,
    min_universe: int | None = None,
    check_m2: bool = False,
) -> int:
    """对区间每个交易日跑 smoke；全部通过返回 0。"""
    days = calendar.trading_days_between(start, end)
    if not days:
        print(f"SMOKE FAIL: 区间内无交易日 {start}~{end}")
        return 1
    failed: list[str] = []
    for i, d in enumerate(days, 1):
        print(f"\n===== smoke [{i}/{len(days)}] {d} =====")
        rc = run_smoke(
            d,
            code=code,
            require_published=require_published,
            min_universe=min_universe,
            check_m2=check_m2,
        )
        if rc != 0:
            failed.append(d.isoformat())
    if failed:
        print(f"\nSMOKE RANGE FAIL: {len(failed)}/{len(days)} days")
        print("failed:", ", ".join(failed[:20]) + (" ..." if len(failed) > 20 else ""))
        return 1
    print(f"\nSMOKE RANGE OK: {len(days)}/{len(days)} days green")
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description="qdata 研究入口冒烟测试")
    p.add_argument("--date", type=dt.date.fromisoformat, default=None)
    p.add_argument("--start", type=dt.date.fromisoformat, default=None)
    p.add_argument("--end", type=dt.date.fromisoformat, default=None)
    p.add_argument("--code", default="600000.SH", help="抽样股票代码")
    p.add_argument(
        "--prod",
        action="store_true",
        help="生产验收：必须已发布 + universe≥QDATA_PROD_MIN_UNIVERSE",
    )
    p.add_argument(
        "--check-m2",
        action="store_true",
        help="附加指数/行业/因子/读数层软检查",
    )
    p.add_argument(
        "--min-universe",
        type=int,
        default=None,
        help="覆盖最小股票池（默认联调=1，--prod 时读配置）",
    )
    args = p.parse_args(argv)

    require_published = bool(args.prod)
    min_uni = args.min_universe
    if args.prod and min_uni is None:
        min_uni = prod_min_universe()
    check_m2 = bool(args.check_m2 or args.prod)

    if args.start and args.end:
        sys.exit(
            run_smoke_range(
                args.start,
                args.end,
                code=args.code,
                require_published=require_published,
                min_universe=min_uni,
                check_m2=check_m2,
            )
        )
    if args.date is None:
        p.error("请提供 --date，或同时提供 --start 与 --end")
    sys.exit(
        run_smoke(
            args.date,
            args.code,
            require_published=require_published,
            min_universe=min_uni if args.prod else args.min_universe,
            check_m2=check_m2,
        )
    )


if __name__ == "__main__":
    main()
