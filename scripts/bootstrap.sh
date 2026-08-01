#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3.12}"

"$python_bin" -m venv "$repo_dir/.venv"
"$repo_dir/.venv/bin/python" -m pip install -r "$repo_dir/requirements-dev.txt"
npm --prefix "$repo_dir/apps/desktop" install

echo "Bootstrap complete."

