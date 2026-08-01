from pathlib import Path

from app.database import CandidateRepository
from app.models import CandidateCreate, CandidateUpdate, ScoreInput
from app.scoring import StrategyEngine


ROOT = Path(__file__).parents[1]
STRATEGY = ROOT / "packages" / "strategy-spec" / "group-original-v1.json"


def payload() -> CandidateCreate:
    return CandidateCreate(score_input=ScoreInput(
        stock_code="sh600519", stock_name="贵州茅台", sector="食品", price=1500,
        pe=24, pb=8, pe_percentile=.4, pb_percentile=.7, change_pct=1,
        turnover_pct=.3, amplitude_pct=2, main_flow_ratio=.03,
    ), note="等待确认")


def test_candidate_survives_repository_restart(tmp_path):
    db_path = tmp_path / "research.sqlite3"
    request = payload()
    result = StrategyEngine(STRATEGY).score(request.score_input)
    created = CandidateRepository(db_path).create(request, result)
    reopened = CandidateRepository(db_path)
    stored = reopened.get(created.id)
    assert stored.stock_code == "sh600519"
    assert stored.note == "等待确认"
    assert stored.dimensions


def test_candidate_status_can_be_updated(tmp_path):
    repo = CandidateRepository(tmp_path / "research.sqlite3")
    request = payload()
    created = repo.create(request, StrategyEngine(STRATEGY).score(request.score_input))
    updated = repo.update(created.id, CandidateUpdate(status="watching"))
    assert updated.status == "watching"

