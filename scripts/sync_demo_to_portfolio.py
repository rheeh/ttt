"""Copy the static demo into an explicitly selected portfolio checkout."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("portfolio", type=Path, help="Portfolio repository root")
args = parser.parse_args()
root = args.portfolio.resolve()
if not (root / "src/data/profile.ts").is_file():
    parser.error("Expected a portfolio checkout containing src/data/profile.ts")
source = Path(__file__).resolve().parents[1] / "demo"
target = root / "public/projects/zhixing"
target.mkdir(parents=True, exist_ok=True)
for name in ("index.html", "style.css", "app.js", "data.js", "favicon.svg"):
    shutil.copy2(source / name, target / name)
print(f"Synced 5 demo assets to {target}")
