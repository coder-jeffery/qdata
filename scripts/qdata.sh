#!/usr/bin/env bash
# Wrapper: always put src on PYTHONPATH, then run project venv python.
# Usage: ./scripts/qdata.sh -m qdata.loaders.security_master --date 2026-07-15 --fetch
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${ROOT}/.venv/bin/python" "$@"
