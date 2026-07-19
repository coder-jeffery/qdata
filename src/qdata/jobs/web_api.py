"""启动 Web BFF：python -m qdata.jobs.web_api [--port 8787]"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="qdata Web BFF (FastAPI)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    import uvicorn

    uvicorn.run(
        "qdata.api.bff:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
