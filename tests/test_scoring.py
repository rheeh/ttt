from pathlib import Path

from app.models import ScoreInput
from app.scoring import StrategyEngine


STRATEGY = Path(__file__).parents[1] / "packages" / "strategy-spec" / "group-original-v1.json"


def sample(**overrides) -> ScoreInput:
    values = {
        "stock_code": "sh603501", "stock_name": "样例股", "sector": "半导体", "price": 100,
        "pe": 25, "pb": 2, "pe_percentile": .2, "pb_percentile": .2,
        "change_pct": 1.8, "turnover_pct": 3.5, "amplitude_pct": 4,
        "main_flow_ratio": .06, "sector_change_pct": 3.5, "quality_score": 4,
        "ma5": 98, "ma10": 95, "ma20": 90, "in_rotation_pool": True,
    }
    values.update(overrides)
    return ScoreInput(**values)


def test_strong_candidate_has_explainable_s_grade():
    result = StrategyEngine(STRATEGY).score(sample())
    assert result.eligible is True
    assert result.grade == "S"
    assert result.total_score == sum(item.score for item in result.dimensions)
    assert {item.name for item in result.dimensions} == {
        "valuation", "price_momentum", "sector", "capital_flow", "trend", "risk", "quality"
    }


def test_strategy_filters_chinext_without_destroying_score():
    result = StrategyEngine(STRATEGY).score(sample(stock_code="sz300001"))
    assert result.eligible is False
    assert result.rejected_reasons == ["市场前缀被策略过滤"]
    assert result.total_score > 0


def test_valuation_penalty_is_capped_at_minus_three():
    result = StrategyEngine(STRATEGY).score(sample(pe=150, pe_percentile=.95, pb_percentile=.95))
    valuation = next(item for item in result.dimensions if item.name == "valuation")
    assert valuation.score == -3
    assert "估值惩罚下限-3" in valuation.reasons

