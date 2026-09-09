#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="$ROOT/services/forge-engine"
VENV="$ENGINE/.venv"
PYTHON="$VENV/bin/python"

echo "ForgeCAD v2 — macOS bootstrap (secondary platform)"
if [[ ! -x "$PYTHON" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then python3.12 -m venv "$VENV";
  elif command -v python3 >/dev/null 2>&1; then python3 -m venv "$VENV";
  else echo "Python 3.12 is required." >&2; exit 1; fi
fi
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -e "$ENGINE"
cd "$ROOT"
corepack enable
pnpm install
printf '\nmacOS runtime ready. Run: pnpm dev\n'
printf 'macOS default Ollama model: qwen3:8b\n'
