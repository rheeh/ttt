from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_data_dir() -> Path:
    configured = os.getenv("STOCK_RESEARCH_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ZhixingStockResearch"
    return Path.home() / ".local" / "share" / "zhixing-stock-research"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    strategy_path: Path
    stock_pool_path: Path


def get_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[3]
    data_dir = default_data_dir()
    return Settings(
        data_dir=data_dir,
        database_path=data_dir / "research.sqlite3",
        strategy_path=repo_root / "packages" / "strategy-spec" / "group-original-v1.json",
        stock_pool_path=repo_root / "packages" / "stock-presets" / "group-original-pool.json",
    )
