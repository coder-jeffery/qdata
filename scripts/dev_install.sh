#!/usr/bin/env bash
# Install qdata in editable mode and fix macOS/Python 3.14 import path issues.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "python3 not found" >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    uv venv "$ROOT/.venv"
    PY="$ROOT/.venv/bin/python"
  fi
  uv pip install -e ".[dev]" --python "$PY"
else
  "$PY" -m pip install -e ".[dev]"
fi

"$PY" "$ROOT/scripts/ensure_import_path.py"
echo "dev install complete"
