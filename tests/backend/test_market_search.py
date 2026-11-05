"""P2-03 acceptance tests: GET /api/v1/market/search (SRCH-01 to SRCH-05).

Every answer is a ``market-envelope-v1`` body with HTTP 200. The tests inject
in-memory name sources, so nothing here opens a socket, reads the user data
cache or creates a jobs database; SRCH-04 asserts that absence explicitly.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import create_app  # noqa: E402
from backend.app.services.job_service import CST  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.ticker_directory import (  # noqa: E402
    DiskNameCache,
    TickerDirectory,
)

NAMES = {
    "600519": "贵州茅台",
    "000858": "五粮液",
    "300750": "宁德时代",
    "000001": "平安银行",
    "601318": "中国平安",
    "600000": "浦发银行",
    "601398": "工商银行",
    "601988": "中国银行",
}

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=CST)


class _StubService:
    """create_app only needs an engine and a clock to build the SSE stream."""

    engine = None

    def now(self) -> datetime:
        return NOW

    def __getattr__(self, name: str):
        raise AssertionError(f"search must not touch the job service: {name}")


def _client(tmp_path: Path, source=None) -> TestClient:
    directory = TickerDirectory(source, clock=lambda: NOW)
    app = create_app(
        service=_StubService(),
        report_store=ReportStore(tmp_path / "reports"),
        ticker_directory=directory,
    )
    return TestClient(app)


@pytest.fixture()
def client(tmp_path):
    with _client(tmp_path, NAMES) as test_client:
        yield test_client


def _search(client: TestClient, q: str, **params) -> dict:
    response = client.get("/api/v1/market/search", params={"q": q, **params})
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "market-envelope-v1"
    assert payload["partial"] is False
    assert payload["failed_blocks"] == []
    assert payload["is_stale"] is (payload["status"] == "stale")
    return payload


def _codes(payload: dict) -> list[str]:
    return [item["ticker_code"] for item in payload["data"]["items"]]


# SRCH-01 ---------------------------------------------------------------


def test_code_full_name_and_partial_name_hits(client):
    by_code = _search(client, "600519")
    assert by_code["status"] == "ok"
    assert by_code["data"] == {
        "items": [{"ticker_code": "600519", "ticker_name": "贵州茅台", "market": "sh"}],
        "truncated": False,
    }

    by_full_name = _search(client, "宁德时代")
    assert _codes(by_full_name) == ["300750"]
    assert by_full_name["data"]["items"][0]["market"] == "sz"

    by_partial = _search(client, "银行")
    assert _codes(by_partial) == ["000001", "600000", "601398", "601988"]
    assert [item["market"] for item in by_partial["data"]["items"]] == [
        "sz",
        "sh",
        "sh",
        "sh",
    ]


def test_truncated_flag_tracks_the_unclipped_match_count(client):
    two = _search(client, "银行", limit=2)
    assert _codes(two) == ["000001", "600000"]
    assert two["data"]["truncated"] is True

    exact = _search(client, "银行", limit=4)
    assert len(_codes(exact)) == 4
    assert exact["data"]["truncated"] is False


# SRCH-02 ---------------------------------------------------------------


def test_empty_query_returns_empty_envelope(client):
    for q in ("", "   ", "\u3000"):
        payload = _search(client, q)
        assert payload["status"] == "empty"
        assert payload["data"] is None
        assert payload["as_of"] is None
        assert payload["error_code"] is None
        assert payload["is_stale"] is False


def test_multiple_candidates_use_frozen_ordering(client):
    payload = _search(client, "平安")
    assert _codes(payload) == ["000001", "601318"]

    chinese = _search(client, "中国")
    assert _codes(chinese) == ["601318", "601988"]


def test_code_prefix_is_accepted_for_exact_hits(client):
    payload = _search(client, "SH600519")
    assert _codes(payload) == ["600519"]
    assert payload["data"]["truncated"] is False


def test_unmatched_query_is_a_successful_empty_page(client):
    payload = _search(client, "不存在的股票")
    assert payload["status"] == "ok"
    assert payload["data"] == {"items": [], "truncated": False}


# SRCH-03 ---------------------------------------------------------------


class _FailingSource:
    label = "broken"

    def load(self):
        raise RuntimeError("name table is gone")


class _TimeoutSource:
    label = "slow"

    def load(self):
        raise TimeoutError("name table timed out")


def test_source_failure_returns_upstream_error(tmp_path):
    with _client(tmp_path, _FailingSource()) as client:
        response = client.get("/api/v1/market/search", params={"q": "茅台"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "error"
        assert payload["error_code"] == "upstream_error"
        assert payload["error_message"]
        assert payload["data"] is None
        assert payload["as_of"] is None


def test_source_timeout_returns_upstream_timeout(tmp_path):
    with _client(tmp_path, _TimeoutSource()) as client:
        payload = _search(client, "茅台")
        assert payload["status"] == "error"
        assert payload["error_code"] == "upstream_timeout"
        assert payload["error_message"]


# SRCH-04 ---------------------------------------------------------------


def test_search_writes_nothing(tmp_path):
    reports = tmp_path / "reports"
    with _client(tmp_path, NAMES) as client:
        for q in ("600519", "", "不存在的股票"):
            assert _search(client, q)["status"] in ("ok", "empty")

    assert list(tmp_path.iterdir()) == []
    assert not reports.exists()


# SRCH-05 ---------------------------------------------------------------


def test_limit_defaults_to_ten_and_clamps_at_fifty(tmp_path):
    names = {f"{code:06d}": f"测试{code}" for code in range(1, 61)}
    with _client(tmp_path, names) as client:
        default = _search(client, "测试")
        assert len(_codes(default)) == 10
        assert default["data"]["truncated"] is True

        fifty = _search(client, "测试", limit=50)
        assert len(_codes(fifty)) == 50
        assert fifty["data"]["truncated"] is True

        clamped = _search(client, "测试", limit=500)
        assert len(_codes(clamped)) == 50

        single = _search(client, "测试", limit=0)
        assert len(_codes(single)) == 1


# Disk source -----------------------------------------------------------


def _write_cache(root: Path, stamp: str, names: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"name-code-map-{stamp}.json"
    payload = {"n2c": {name: code for code, name in names.items()}, "c2n": names}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_disk_source_reads_the_newest_daily_table(tmp_path):
    cache = tmp_path / "cache"
    _write_cache(cache, "20261104", {"600519": "旧名称"})
    _write_cache(cache, "20261105", {"600519": "贵州茅台"})

    directory = TickerDirectory(DiskNameCache(cache), clock=lambda: NOW)
    result = directory.search("茅台")
    assert result.status == "ok"
    assert result.source == "mootdx-cache"
    assert result.as_of == "2026-11-05"
    assert result.items[0]["ticker_name"] == "贵州茅台"


def test_missing_disk_cache_is_an_upstream_error_without_creating_it(tmp_path):
    cache = tmp_path / "cache"
    directory = TickerDirectory(DiskNameCache(cache), clock=lambda: NOW)
    result = directory.search("茅台")
    assert result.status == "error"
    assert result.error_code == "upstream_error"
    assert not cache.exists()
    assert directory.name("600519") is None


def test_disk_cache_older_than_a_day_is_stale_but_searchable(tmp_path):
    cache = tmp_path / "cache"
    _write_cache(cache, "20261101", {"600519": "贵州茅台"})

    directory = TickerDirectory(DiskNameCache(cache), clock=lambda: NOW)
    result = directory.search("茅台")
    assert result.status == "stale"
    assert result.stale_reason == "ttl_exceeded"
    assert result.as_of == "2026-11-01"
    assert result.items[0]["ticker_code"] == "600519"


def test_static_names_are_never_stale(tmp_path):
    directory = TickerDirectory({"600519": "贵州茅台"}, clock=lambda: NOW)
    later = TickerDirectory(
        {"600519": "贵州茅台"},
        clock=lambda: NOW + timedelta(days=3),
    )
    assert directory.search("茅台").status == "ok"
    assert later.search("茅台").status == "ok"
