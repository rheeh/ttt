#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' EXIT INT TERM

PYTHONPATH="$repo_dir/services/desktop-api" \
  "$repo_dir/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8765 --reload &
npm --prefix "$repo_dir/apps/desktop" run dev

