"""Dashboard 数据层单测（不依赖 streamlit UI）。"""

from qdata.dashboard.data import list_runs, load_run_detail, lake_runs_root


def test_list_runs_smoke():
    runs = list_runs(limit=5)
    assert isinstance(runs, list)
    # 有历史 run 时校验字段
    if runs:
        r = runs[0]
        assert r.run_id
        assert r.source in ("ch", "lake")


def test_load_run_detail_if_any():
    runs = list_runs(limit=1)
    if not runs:
        # 无 run 时至少 Lake 根路径可解析
        assert lake_runs_root().name == "runs"
        return
    detail = load_run_detail(runs[0].run_id)
    assert "meta" in detail
    assert "metrics" in detail
    assert "equity" in detail
