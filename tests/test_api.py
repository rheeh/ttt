from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_score_api(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCK_RESEARCH_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["storage"] == "local-sqlite"
        response = client.post("/api/score", json={
            "stock_code": "sh603501", "stock_name": "样例股", "sector": "半导体", "price": 100,
            "pe": 25, "pb": 2, "pe_percentile": .2, "pb_percentile": .2,
            "change_pct": 1.8, "turnover_pct": 3.5, "amplitude_pct": 4,
            "main_flow_ratio": .06, "sector_change_pct": 3.5, "quality_score": 4,
        })
        assert response.status_code == 200
        assert response.json()["grade"] == "S"
        review = client.get("/api/market/review")
        assert review.status_code == 200
        assert review.json()["run_id"] is None
        verification = client.post("/api/candidates/performance/verify")
        assert verification.status_code == 200
        assert verification.json()["processed"] == 0
        sources = client.get("/api/health/sources")
        assert sources.status_code == 200 and sources.json()["sources"] == []
