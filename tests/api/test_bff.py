"""BFF 冒烟：不依赖 ClickHouse 可用性（失败返回空结构也可）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from qdata.api.bff import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_overview_shape() -> None:
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert "dataset" in body
    assert "paper" in body
    assert "factor_monitor" in body


def test_paper_sessions_list() -> None:
    r = client.get("/api/paper/sessions?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "count" in body


def test_data_health_shape() -> None:
    r = client.get("/api/data/health")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "lag" in body


def test_experiments_list() -> None:
    r = client.get("/api/experiments?limit=5")
    assert r.status_code == 200
    assert "items" in r.json()


def test_signals_list() -> None:
    r = client.get("/api/signals?limit=5")
    assert r.status_code == 200
    assert "items" in r.json()


def test_factors_coverage_shape() -> None:
    r = client.get("/api/factors/coverage")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "dates" in body


def test_monitor_latest() -> None:
    r = client.get("/api/monitor")
    assert r.status_code == 200
    body = r.json()
    assert "report" in body
    assert "dates" in body


def test_backtests_shape() -> None:
    r = client.get("/api/backtests?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "matrix" in body


def test_finance_shape() -> None:
    r = client.get("/api/data/finance")
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "pit" in body


def test_universe_shape() -> None:
    r = client.get("/api/research/universe")
    assert r.status_code == 200
    body = r.json()
    assert "sizes" in body
    assert "industry" in body


def test_judgment_endpoint() -> None:
    r = client.get("/api/research/judgment/600519.SH")
    # CH 不可用时也可能 400；存在则 200
    assert r.status_code in (200, 400)


def test_alerts_shape() -> None:
    r = client.get("/api/alerts")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "count" in body
    assert "n_error" in body


def test_jobs_list() -> None:
    r = client.get("/api/jobs?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "count" in body


def test_enqueue_unknown_job() -> None:
    r = client.post("/api/jobs", json={"type": "not_a_real_job", "payload": {}})
    assert r.status_code == 400


def test_realtime_quotes_shape() -> None:
    r = client.get("/api/realtime/quotes")
    assert r.status_code == 200
    body = r.json()
    assert "quotes" in body
    assert "source" in body
    assert "n" in body


def test_enqueue_realtime_job() -> None:
    from qdata.api.job_queue import register_default_handlers

    register_default_handlers()
    r = client.post(
        "/api/jobs",
        json={"type": "realtime_snapshot", "payload": {"source": "easyquotation", "codes": []}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("job_id")
    assert body.get("status") == "queued"
    # poll once
    jr = client.get(f"/api/jobs/{body['job_id']}")
    assert jr.status_code == 200
    assert jr.json()["job_id"] == body["job_id"]
