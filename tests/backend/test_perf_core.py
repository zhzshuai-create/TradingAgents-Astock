"""PF-01..PF-06: P6-05 性能门禁的纯函数用例，不需要浏览器。

直接按路径加载 ``scripts/perf_core.py``，避免给 ``tests/`` 引入包结构。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "perf_core.py"
spec = importlib.util.spec_from_file_location("perf_core", MODULE_PATH)
perf_core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf_core)

VIEWPORTS = ("mobile", "desktop")
INTERACTIONS = perf_core.INTERACTIONS


def make_samples(*, lcp=1200.0, cls=0.02, inp=90.0, n=20):
    samples = {}
    for viewport in VIEWPORTS:
        per = {name: [inp] * max(1, n // len(INTERACTIONS)) for name in INTERACTIONS}
        flat = [value for values in per.values() for value in values]
        while len(flat) < n:
            per[INTERACTIONS[0]].append(inp)
            flat.append(inp)
        samples[viewport] = {
            "lcp_ms": [lcp] * n,
            "cls": [cls] * n,
            "inp_ms": flat,
            "inp_by_interaction": per,
        }
    return samples


def build_doc(samples):
    return perf_core.build_evidence(
        measured_at="2026-11-08T15:00:00+08:00",
        command="perf_core.py --samples 20",
        build_info={
            "manifest": "frontend/dist/.vite/manifest.json",
            "mtime": "2026-11-08T15:09:15+08:00",
        },
        samples=samples,
        samples_per_viewport=20,
        request_urls=["http://127.0.0.1:4000/api/v1/jobs"],
        external_requests=[],
    )


def test_pf01_six_lines_present_and_parseable():
    doc, failed = build_doc(make_samples())
    assert failed is False
    parsed = json.loads(json.dumps(doc, ensure_ascii=False))
    for viewport in VIEWPORTS:
        metrics = parsed["metrics"][viewport]
        assert set(metrics) == set(perf_core.REGRESSION)
        for metric, entry in metrics.items():
            assert isinstance(entry["target"], (int, float))
            assert isinstance(entry["regression"], (int, float))
            assert entry["target"] == perf_core.TARGET[metric]
            assert entry["regression"] == perf_core.REGRESSION[metric]
    # 六条线 = 三条指标 × (目标线 + 回归线)，视口各复用同一组线。
    assert len(perf_core.REGRESSION) * 2 == 6


def test_pf02_requires_twenty_samples():
    short = make_samples(n=19)
    report, failed = perf_core.judge(short)
    assert failed is True
    for viewport in VIEWPORTS:
        for metric in perf_core.REGRESSION:
            entry = report[viewport][metric]
            assert entry["pass"] is False
            assert entry["reason"] == "samples<20"

    _, ok_failed = perf_core.judge(make_samples(n=20))
    assert ok_failed is False


def test_pf03_below_passes_above_fails_and_exit_code():
    below, below_failed = perf_core.judge(make_samples(lcp=2400, cls=0.09, inp=190))
    assert below_failed is False
    for viewport in VIEWPORTS:
        assert below[viewport]["lcp_ms"]["pass"] is True
        assert below[viewport]["lcp_ms"]["warn"] is True

    above, above_failed = perf_core.judge(make_samples(lcp=2600, cls=0.11, inp=210))
    assert above_failed is True
    for viewport in VIEWPORTS:
        for metric in perf_core.REGRESSION:
            assert above[viewport][metric]["pass"] is False

    assert perf_core.exit_code(True) == 1
    assert perf_core.exit_code(False) == 0


def test_pf04_missing_interaction_fails():
    samples = make_samples()
    samples["mobile"]["inp_by_interaction"]["list_filter"] = []
    report, failed = perf_core.judge(samples)
    assert failed is True
    assert report["mobile"]["inp_by_interaction"]["list_filter"]["samples"] == 0

    good_report, good_failed = perf_core.judge(make_samples())
    assert good_failed is False
    for viewport in VIEWPORTS:
        for name in INTERACTIONS:
            assert good_report[viewport]["inp_by_interaction"][name]["samples"] > 0


def test_pf05_evidence_records_samples_p75_lines_and_definitions():
    doc, _ = build_doc(make_samples(lcp=1234.0, cls=0.021, inp=88.0))
    assert doc["samples_per_viewport"] == 20
    for viewport in VIEWPORTS:
        for metric, entry in doc["metrics"][viewport].items():
            assert entry["p75"] is not None
            assert entry["target"] == perf_core.TARGET[metric]
            assert entry["regression"] == perf_core.REGRESSION[metric]
            assert entry["samples"] >= 20
    assert set(doc["interaction_definitions"]) == set(INTERACTIONS)
    for name in INTERACTIONS:
        assert doc["interaction_definitions"][name]


def test_pf06_only_stubbed_same_origin_requests():
    base = "http://127.0.0.1:51234"
    allowed = [
        f"{base}/assets/app.js",
        f"{base}/api/v1/market/overview",
        "data:image/png;base64,AA==",
    ]
    assert perf_core.classify_requests(allowed, base) == []

    external = perf_core.classify_requests(
        [f"{base}/api/v1/jobs", "https://cdn.example.com/x.js"], base
    )
    assert external == ["https://cdn.example.com/x.js"]

    doc, _ = build_doc(make_samples())
    assert doc["requests"]["external"] == []


def test_p75_nearest_rank():
    assert perf_core.p75([1, 2, 3, 4]) == 3
    assert perf_core.p75(range(1, 21)) == 15
    assert perf_core.p75([0.05]) == 0.05
