from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import AllAMarketSnapshot


class AllAMarketSnapshotProvider:
    """Fetch whole-A spot data without importing the strategy scanner."""

    name = "akshare-spot-em-all-a"

    def fetch(self) -> AllAMarketSnapshot:
        snapshot_at = datetime.now(timezone.utc)
        try:
            import akshare as ak

            frame = ak.stock_zh_a_spot_em()
            return self.from_rows(frame.to_dict("records"), snapshot_at)
        except Exception as exc:
            return AllAMarketSnapshot(
                snapshot_at=snapshot_at, source=self.name, data_status="error",
                degraded_reasons=[f"全 A 现货接口获取失败：{exc}"],
            )

    @classmethod
    def from_rows(cls, rows: list[dict[str, Any]], snapshot_at: datetime | None = None) -> AllAMarketSnapshot:
        snapshot_at = snapshot_at or datetime.now(timezone.utc)
        valid: list[float] = []
        for row in rows:
            code = str(row.get("代码") or "").zfill(6)
            change = cls._number(row.get("涨跌幅"))
            price = cls._number(row.get("最新价"))
            if len(code) == 6 and price is not None and price > 0 and change is not None:
                valid.append(change)
        total = len(rows)
        coverage = len(valid)
        up = sum(value > 0 for value in valid)
        down = sum(value < 0 for value in valid)
        flat = coverage - up - down
        reasons = ["现货接口未提供明确交易日，交易日需由日线快照补齐"]
        if coverage < total:
            reasons.append(f"涨跌字段有效 {coverage}/{total}")
        # The spot endpoint does not carry an authoritative trade date, so it
        # cannot be advertised as a fully complete daily snapshot yet.
        status = "degraded" if coverage else "error"
        return AllAMarketSnapshot(
            snapshot_at=snapshot_at, source=cls.name, data_status=status,
            total=total, coverage_count=coverage, coverage_total=total,
            coverage_pct=round(coverage / total * 100, 2) if total else None,
            up_count=up, down_count=down, flat_count=flat,
            sample_up_rate_pct=round(up / coverage * 100, 2) if coverage else None,
            average_change_pct=round(sum(valid) / coverage, 4) if valid else None,
            degraded_reasons=reasons,
        )

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value not in (None, "", "-") else None
        except (TypeError, ValueError):
            return None
