#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "未找到 .venv。请先运行 bash scripts/dev.sh 或按 README 创建虚拟环境。" >&2
  exit 1
fi

PYTHON="$ROOT/.venv/bin/python"
export PYTHONPATH="$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"
export MYPYPATH="$ROOT/apps/api${MYPYPATH:+:$MYPYPATH}"

"$PYTHON" -m unittest discover -s apps/api/tests -v
"$PYTHON" -m compileall -q apps/api/app apps/api/tests scripts
"$PYTHON" -m ruff check apps/api/app apps/api/tests scripts
"$PYTHON" -m mypy apps/api/app scripts
