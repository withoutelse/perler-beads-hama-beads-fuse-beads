#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON="$PYTHON_BIN"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON="python3.12"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "未找到 Python 3.12+。请先安装 Python 3.12 或更高版本。" >&2
  exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
  echo "需要 Python 3.12+，当前命令：$PYTHON" >&2
  "$PYTHON" --version >&2 || true
  exit 1
fi

if [[ -d "$ROOT/.venv" && ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "检测到不兼容的 .venv（可能由 Windows 创建）。请删除 .venv 后重试。" >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "创建虚拟环境 .venv ..."
  "$PYTHON" -m venv "$ROOT/.venv"
fi

VENV_PYTHON="$ROOT/.venv/bin/python"
if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
  echo "现有 .venv 不是 Python 3.12+。请删除 .venv 后重试。" >&2
  exit 1
fi

echo "安装后端依赖 ..."
"$VENV_PYTHON" -m pip install -e "apps/api[dev]"

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "已创建 .env。真实 Tripo 重建前请填写 TRIPO_API_KEY。"
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "未找到 pnpm。请先运行：npm install -g pnpm" >&2
  exit 1
fi

echo "安装前端依赖 ..."
(cd "$ROOT/apps/web" && pnpm install)

echo "启动 API ..."
"$VENV_PYTHON" -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload &
API_PID=$!

cleanup() {
  if kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "API: http://127.0.0.1:8000"
echo "Frontend: http://localhost:5173"
echo "按 Ctrl+C 停止前后端。"

cd "$ROOT/apps/web"
pnpm run dev
