"""Raw 区：不可变 Parquet 数据湖 + manifest 登记。

目录：<lake_root>/raw/<source>/<dataset>/dt=<YYYY-MM-DD>/data.parquet
规则：同一分区重复写入直接覆盖整个分区文件（拉取本身幂等），
      但绝不在文件内做部分修改；清洗逻辑一律在 Loader 层做。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from qdata.config import settings


def _partition_dir(source: str, dataset: str, date: dt.date) -> Path:
    return settings().lake_root / "raw" / source / dataset / f"dt={date.isoformat()}"


def write_raw(source: str, dataset: str, date: dt.date, df: pd.DataFrame) -> Path:
    """落盘一个分区并登记 manifest，返回文件路径。"""
    if df is None:
        df = pd.DataFrame()
    if df.empty and len(df.columns) == 0:
        raise ValueError(
            f"拒绝写入无 schema 的空 DataFrame: {source}/{dataset}/dt={date}。"
            f"Fetcher 应返回带列名的空表，或在全失败时抛错。"
        )

    pdir = _partition_dir(source, dataset, date)
    pdir.mkdir(parents=True, exist_ok=True)
    path = pdir / "data.parquet"
    df.to_parquet(path, index=False)

    _append_manifest({
        "ts": time.time(),
        "source": source,
        "dataset": dataset,
        "dt": date.isoformat(),
        "rows": len(df),
        "md5": hashlib.md5(path.read_bytes()).hexdigest(),
    })
    return path


def read_raw(source: str, dataset: str, date: dt.date) -> pd.DataFrame:
    path = _partition_dir(source, dataset, date) / "data.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Raw 分区不存在: {path}（先运行 fetch 任务）")
    return pd.read_parquet(path)


def raw_row_count(source: str, dataset: str, date: dt.date) -> int | None:
    """分区存在则返回行数，否则 None。"""
    path = _partition_dir(source, dataset, date) / "data.parquet"
    if not path.exists():
        return None
    try:
        import pyarrow.parquet as pq

        return int(pq.read_metadata(path).num_rows)
    except Exception:
        return int(len(pd.read_parquet(path)))


def read_raw_any(
    dataset: str,
    date: dt.date,
    sources: list[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """按候选 source 顺序读取，返回 (df, 实际 source)。"""
    from qdata.fetchers.factory import raw_source_candidates

    candidates = sources or raw_source_candidates()
    errors: list[str] = []
    for src in candidates:
        path = _partition_dir(src, dataset, date) / "data.parquet"
        if not path.exists():
            errors.append(f"{src}: missing {path}")
            continue
        df = pd.read_parquet(path)
        return df, src
    raise FileNotFoundError(
        f"Raw 分区不存在（已试 source={candidates}）dataset={dataset} date={date}\n"
        + "\n".join(errors)
    )


def _append_manifest(record: dict) -> None:
    mpath = settings().lake_root / "meta" / "_manifest.jsonl"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
