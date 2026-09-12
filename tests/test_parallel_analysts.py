"""Topology tests for analyst orchestration (serial chain vs parallel fan-out).

Parallel mode (config "parallel_analysts") runs all analysts in one LangGraph
super-step, each with its own <type>_messages channel so tool-call routing is
unambiguous. Default remains the serial chain (zero behavior change).
"""

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

_ANALYST_NODES = ["Market", "Social", "News", "Fundamentals", "Policy", "Hot_money", "Lockup"]
_ANALYST_KEYS = ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"]


def _build(parallel: bool):
    cfg = {**DEFAULT_CONFIG, "parallel_analysts": parallel, "llm_provider": "openai"}
    tg = TradingAgentsGraph(debug=False, config=cfg)
    return {(e.source, e.target) for e in tg.graph.get_graph().edges}


def _edges_checks(edges):
    start_targets = {t for s, t in edges if s == "__start__"}
    clears_to_qg = all(
        (f"Msg Clear {a}", "Quality Gate") in edges for a in _ANALYST_NODES
    )
    chained = any(
        (f"Msg Clear {a}", f"{b} Analyst") in edges
        for a, b in zip(_ANALYST_NODES, _ANALYST_NODES[1:])
    )
    tool_loops = all(
        (f"{a} Analyst", f"tools_{k}") in edges
        and (f"tools_{k}", f"{a} Analyst") in edges
        for a, k in zip(_ANALYST_NODES, _ANALYST_KEYS)
    )
    return start_targets, clears_to_qg, chained, tool_loops


@pytest.mark.unit
def test_serial_topology_is_chain():
    edges = _build(False)
    start_targets, clears_to_qg, chained, tool_loops = _edges_checks(edges)
    assert start_targets == {"Market Analyst"}
    assert chained
    assert not clears_to_qg
    assert tool_loops


def test_parallel_topology_fans_out():
    edges = _build(True)
    start_targets, clears_to_qg, chained, tool_loops = _edges_checks(edges)
    assert start_targets == {f"{a} Analyst" for a in _ANALYST_NODES}
    assert clears_to_qg
    assert not chained
    assert tool_loops


def test_default_config_is_serial():
    assert DEFAULT_CONFIG["parallel_analysts"] is False
