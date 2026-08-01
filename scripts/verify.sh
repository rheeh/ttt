#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
PYTHONPATH="$repo_dir/services/desktop-api" "$repo_dir/.venv/bin/python" -m pytest
npm --prefix "$repo_dir/apps/desktop" run lint
npm --prefix "$repo_dir/apps/desktop" run build

