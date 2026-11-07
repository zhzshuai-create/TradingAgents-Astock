"""P6-04pre acceptance: the real executor maps graph super-steps to stages.

RR-01 double switch selects the real executor, construction builds no client.
RR-02 the stub graph produces 12 ordered started/done pairs.
RR-03 a parallel step splits its stats delta across the stages it completes.
RR-04 resume fails fast before the graph is touched.
RR-05 the report DTO keeps job-owned meta empty for ``finalize_report``.
RR-06 stage ids, names and report keys match ``web.progress``; backend does
      not import ``web``.
RR-07 config precedence and stage toggles.
RR-08 think blocks are stripped and the five flat/nested keys map correctly.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.models.stage import STAGE_IDS, STAGE_NAMES  # noqa: E402
from backend.app.services import stage_map  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    REAL_RUNNER_ENV,
    AnalysisRequest,
    AnalysisRunError,
    FakeAnalysisExecutor,
    create_analysis_executor,
)
from backend.app.services.real_runner import (  # noqa: E402
    RealAnalysisExecutor,
    analysts_for,
    build_real_config,
)

BACKEND = ROOT / "backend"
SNAPSHOT = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}
REQUEST = AnalysisRequest(
    ticker_code="000629",
    analysis_date="2026-11-07",
    job_id="job-rr",
    generated_at=datetime(2026, 11, 7, 10, 0),
    config=SNAPSHOT,
)
ANALYSTS = {
    "market_report": "技术面报告",
    "sentiment_report": "情绪报告",
    "news_report": "新闻报告",
    "fundamentals_report": "基本面报告",
    "policy_report": "政策报告",
    "hot_money_report": "游资报告",
    "lockup_report": "解禁报告",
}


class StubStats:
    def __init__(self) -> None:
        self.llm_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def add(self, calls: int, tokens_in: int, tokens_out: int) -> None:
        self.llm_calls += calls
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    def get_stats(self) -> dict[str, int]:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": 0,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
        }


STEPS = (
    (7, 700, 1400),
    (2, 200, 400),
    (1, 100, 200),
    (3, 300, 600),
    (2, 200, 400),
)


def _states() -> list[dict]:
    base = {
        "company_of_interest": "000629",
        "trade_date": "2026-11-07",
        "messages": [],
    }
    first = {**base, **ANALYSTS}
    second = {
        **first,
        "data_quality_summary": "数据质量正常",
        "investment_debate_state": {
            "bull_history": "看多",
            "judge_decision": "多空均衡",
        },
    }
    third = {**second, "trader_investment_plan": "买入 10%"}
    fourth = {
        **third,
        "risk_debate_state": {"aggressive_history": "加仓", "judge_decision": "控制仓位"},
    }
    fifth = {
        **fourth,
        "final_trade_decision": "**Rating**: Buy\n**Price Target**: 12.5",
    }
    return [first, second, third, fourth, fifth]


class StubGraph:
    def __init__(self, stats: StubStats, states: list[dict]) -> None:
        self._stats = stats
        self._states = states
        self.graph = self
        self.prepared = 0
        self.finalized: dict | None = None
        self.closed = 0

    def prepare_graph_run(self, ticker, trade_date, callbacks=None):
        self.prepared += 1
        return {"messages": []}, {"stream_mode": "values"}, None

    def stream(self, init_state, **args):
        for state, step in zip(self._states, STEPS, strict=True):
            self._stats.add(*step)
            yield state

    def finalize_graph_run(self, ticker, trade_date, final_state):
        self.finalized = final_state
        return "Hold"

    def close_graph_run(self) -> None:
        self.closed += 1


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def _executor(
    states: list[dict] | None = None,
    *,
    config_path: Path | None = None,
) -> tuple[RealAnalysisExecutor, StubGraph, StubStats]:
    stats = StubStats()
    graph = StubGraph(stats, states or _states())
    executor = RealAnalysisExecutor(
        environ={},
        config_path=config_path or Path("missing-llm-config.json"),
        graph_factory=lambda **_: graph,
        stats_factory=lambda: stats,
        clock=Clock(),
    )
    return executor, graph, stats


def test_rr01_double_switch_selects_the_real_executor():
    assert isinstance(
        create_analysis_executor(ServerConfig(), environ={}), FakeAnalysisExecutor
    )
    env_only = create_analysis_executor(
        ServerConfig(), environ={REAL_RUNNER_ENV: "1"}
    )
    assert isinstance(env_only, FakeAnalysisExecutor)
    config_only = create_analysis_executor(
        ServerConfig(real_runner_enabled=True), environ={}
    )
    assert isinstance(config_only, FakeAnalysisExecutor)

    real = create_analysis_executor(
        ServerConfig(real_runner_enabled=True), environ={REAL_RUNNER_ENV: "1"}
    )
    assert isinstance(real, RealAnalysisExecutor)
    assert real.name == "real"


def test_rr02_stub_graph_produces_twelve_ordered_pairs():
    executor, graph, _ = _executor()
    updates = []
    result = executor.run(REQUEST, on_stage=updates.append)

    assert graph.prepared == 1
    assert graph.closed == 1
    assert len(updates) == 24
    started = [item.stage_id for item in updates if item.phase == "started"]
    done = [item.stage_id for item in updates if item.phase == "done"]
    assert started == list(STAGE_IDS)
    assert done == list(STAGE_IDS)
    assert result.stages_completed == STAGE_IDS
    for item in updates:
        assert item.index == STAGE_IDS.index(item.stage_id) + 1
        assert item.total == len(STAGE_IDS)
        assert item.stage_name == STAGE_NAMES[item.stage_id]
    assert all(item.report_text is None for item in updates if item.phase == "started")
    assert all(item.report_text for item in updates if item.phase == "done")
    assert result.stats.model_calls == sum(step[0] for step in STEPS)


def test_rr03_parallel_step_splits_the_delta():
    executor, _, _ = _executor()
    updates = []
    executor.run(REQUEST, on_stage=updates.append)

    done = [item for item in updates if item.phase == "done"]
    first_step = done[: len(ANALYSTS)]
    assert [item.stage_id for item in first_step] == [
        "market",
        "social",
        "news",
        "fundamentals",
        "policy",
        "hot_money",
        "lockup",
    ]
    assert sum(item.model_calls for item in first_step) == STEPS[0][0]
    assert sum(item.tokens_in for item in first_step) == STEPS[0][1]
    assert sum(item.tokens_out for item in first_step) == STEPS[0][2]
    assert all(item.model_calls == 1 for item in first_step)

    assert sum(item.model_calls for item in done) == sum(step[0] for step in STEPS)
    assert sum(item.tokens_in for item in done) == sum(step[1] for step in STEPS)


def test_rr04_resume_fails_fast_before_the_graph(tmp_path):
    def _forbidden(**_):
        raise AssertionError("graph factory must not run on a resume request")

    calls = []
    executor = RealAnalysisExecutor(
        environ={},
        config_path=tmp_path / "none.json",
        graph_factory=lambda **kwargs: calls.append(kwargs) or _forbidden(**kwargs),
        stats_factory=lambda: StubStats(),
    )
    request = AnalysisRequest(
        ticker_code="000629",
        analysis_date="2026-11-07",
        resume_from_stage="trader",
        config=SNAPSHOT,
    )
    with pytest.raises(AnalysisRunError) as excinfo:
        executor.run(request)
    assert excinfo.value.code == "real_resume_unsupported"
    assert calls == []


def test_rr05_report_dto_leaves_job_fields_to_finalize():
    executor, graph, _ = _executor()
    result = executor.run(REQUEST)

    assert graph.finalized is not None
    assert result.signal == "Hold"
    report = result.report
    assert report is not None
    sections = report["sections"]
    for section_id in (
        "sec-decision",
        "sec-market",
        "sec-quality",
        "sec-debate",
        "sec-risk",
    ):
        assert section_id in sections
    meta = report["meta"]
    assert meta["job_id"] is None
    assert meta["generated_at"] is None
    assert meta["origin"] == "legacy_import"
    assert meta["rating"] == "Buy"


def test_rr06_stage_map_matches_web_progress():
    from web.progress import PIPELINE_STAGES

    assert tuple(item["id"] for item in PIPELINE_STAGES) == STAGE_IDS
    assert {item["id"]: item["name"] for item in PIPELINE_STAGES} == STAGE_NAMES
    assert {
        item["id"]: item["report_key"] for item in PIPELINE_STAGES
    } == stage_map.REPORT_KEYS

    forbidden = re.compile(r"^\s*(?:from|import)\s+web\b", re.MULTILINE)
    for path in BACKEND.rglob("*.py"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path


def test_rr07_config_precedence_and_stage_toggles(tmp_path):
    config_path = tmp_path / "llm_config.json"
    config_path.write_text(
        '{"llm_provider": "mimo", "quick_think_llm": "mimo-flash",'
        ' "deep_think_llm": "mimo-pro", "llm_base_url": "https://file.example",'
        ' "parallel_analysts": true}',
        encoding="utf-8",
    )
    environ = {
        "LLM_PROVIDER": "env-provider",
        "QUICK_THINK_LLM": "env-quick",
        "DEEP_THINK_LLM": "env-deep",
        "BACKEND_URL": "https://env.example",
        "TRADINGAGENTS_RESULTS_DIR": str(tmp_path / "logs"),
        "TRADINGAGENTS_CACHE_DIR": str(tmp_path / "cache"),
        "TRADINGAGENTS_MEMORY_LOG_PATH": str(tmp_path / "memory.md"),
    }
    config = build_real_config(
        SNAPSHOT, environ=environ, config_path=config_path
    )
    assert config["llm_provider"] == "mimo"
    assert config["quick_think_llm"] == "mimo-flash"
    assert config["deep_think_llm"] == "mimo-pro"
    assert config["backend_url"] == "https://file.example"
    assert config["results_dir"] == str(tmp_path / "logs")
    assert config["data_cache_dir"] == str(tmp_path / "cache")
    assert config["checkpoint_enabled"] is False
    assert config["parallel_analysts"] is True

    env_config = build_real_config(
        SNAPSHOT, environ=environ, config_path=tmp_path / "absent.json"
    )
    assert env_config["llm_provider"] == "env-provider"
    assert env_config["quick_think_llm"] == "env-quick"
    assert env_config["backend_url"] == "https://env.example"

    off = {
        **SNAPSHOT,
        "parallel_analysts": False,
        "stage_toggles": {"policy": False, "hot_money": False, "lockup": True},
    }
    config = build_real_config(off, environ=environ, config_path=config_path)
    assert config["parallel_analysts"] is False
    assert analysts_for(off) == (
        "market",
        "social",
        "news",
        "fundamentals",
        "lockup",
    )


def test_rr08_think_blocks_and_flat_keys(tmp_path):
    assert stage_map.clean_text("<think>隐藏</think>可见内容") == "可见内容"
    assert stage_map.clean_text(None) == ""

    states = _states()[-1]
    found = stage_map.detected_stages(states)
    assert list(found) == [
        "market",
        "social",
        "news",
        "fundamentals",
        "policy",
        "hot_money",
        "lockup",
        "quality_gate",
        "debate",
        "trader",
        "risk",
        "pm",
    ]
    assert found["quality_gate"] == "数据质量正常"
    assert found["debate"] == "多空均衡"
    assert found["trader"] == "买入 10%"
    assert found["risk"] == "控制仓位"
    assert found["pm"].startswith("**Rating**: Buy")
