#!/bin/bash
# Resolve the real script, even when this shortcut is moved to another folder.
set -euo pipefail
source_path="${BASH_SOURCE[0]}"
while [[ -L "$source_path" ]]; do
  source_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
  link_target="$(readlink "$source_path")"
  if [[ "$link_target" = /* ]]; then source_path="$link_target"; else source_path="$source_dir/$link_target"; fi
done
repo_dir="$(cd -P "$(dirname "$source_path")/.." && pwd)"
export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
if ! "$repo_dir/.venv/bin/python" "$repo_dir/scripts/start_local.py" "$@"; then
  echo "启动未完成，请查看上方原因。按回车关闭。"
  if [[ -t 0 ]]; then read -r _; fi
  exit 1
fi
