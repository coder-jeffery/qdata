"""启动 qdata 统一 Dashboard（健康 / 因子 / 回测）。

用法：
  python -m qdata.jobs.dashboard
  python -m qdata.jobs.dashboard --port 8502
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="启动 qdata Dashboard")
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args(argv)

    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "缺少 streamlit。请安装：\n"
            "  .venv/bin/python -m pip install -e '.[dashboard]'",
            file=sys.stderr,
        )
        sys.exit(1)

    app = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.port",
        str(args.port),
        "--server.address",
        args.host,
        "--browser.gatherUsageStats",
        "false",
    ]
    print(f"Starting dashboard: http://{args.host}:{args.port}")
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
