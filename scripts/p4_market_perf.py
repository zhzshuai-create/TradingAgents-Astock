"""P4-12 performance probe: stock snapshot warm cache and cold provider load.

``--fixture`` builds the app in-process with ``FakeMarketProviders`` and a
frozen clock; it verifies the harness, the sample arithmetic and the hard
lines without touching the network.

    .venv/Scripts/python.exe scripts/p4_market_perf.py \
        --fixture --samples 30 \
        --out docs/upgrade/reviews/2026-11-07_P4-12性能结果.json

``--live`` swaps in ``DefaultMarketProviders``: the warm pass must stay on the
cache, and every cold sample clears ``MarketCache`` first so all three blocks
(quote/valuation/sector) reach the real providers. This mode needs network and
provider access; it is a manual run, never a CI gate.

p95 is nearest-rank over the measured samples (3 warmups are discarded).
Hard lines: warm snapshot <= 1500 ms, cold load <= 4000 ms.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.services.market_cache import MarketCache  # noqa: E402
from backend.app.services.market_clock import CST, format_cst  # noqa: E402
from backend.app.services.market_providers import (  # noqa: E402
    DefaultMarketProviders,
    FakeMarketProviders,
    Fetched,
)
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.ticker_directory import TickerDirectory  # noqa: E402
from tests.backend.stock_helpers import (  # noqa: E402
    NOW,
    QUOTE,
    SECTOR_BLOCKS,
    VALUATION,
)

WARM_LINE_MS = 1500.0
COLD_LINE_MS = 4000.0
TICKER = "600000"
TICKER_NAME = "浦发银行"


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    rank = max(1, -(-95 * len(ordered) // 100))
    return ordered[rank - 1]


def _measure(
    client: TestClient, url: str, *, warmups: int, samples: int
) -> list[float]:
    for _ in range(warmups):
        client.get(url).raise_for_status()
    times: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        response = client.get(url)
        elapsed = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        times.append(elapsed)
    return times


def _measure_cold(
    client: TestClient,
    cache: MarketCache,
    url: str,
    *,
    samples: int,
) -> list[float]:
    times: list[float] = []
    for _ in range(samples):
        cache.clear()
        started = time.perf_counter()
        response = client.get(url)
        elapsed = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        times.append(elapsed)
    return times


class _CountingProviders:
    """Delegates to the live providers and counts one call per block fetch."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: Counter[str] = Counter()

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._inner, name)
        if not callable(attribute):
            return attribute

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls[name] += 1
            return attribute(*args, **kwargs)

        return counted


class _StubJobs:
    engine = None

    def now(self) -> datetime:
        return NOW


class _StubExports:
    def sweep_stale(self) -> int:
        return 0

    def shutdown(self) -> None:
        return None


def _build_client(mode: str, temp: Path) -> tuple[TestClient, Any, MarketCache]:
    clock = lambda: NOW  # noqa: E731 - frozen clock for the name directory
    if mode == "fixture":
        providers: Any = FakeMarketProviders()
        as_of = format_cst(NOW)
        providers.set("quote", Fetched(data=QUOTE, as_of=as_of, source="tencent"))
        providers.set(
            "valuation", Fetched(data=VALUATION, as_of=as_of, source="ths")
        )
        providers.set(
            "sector_blocks",
            Fetched(data=SECTOR_BLOCKS, as_of=as_of, source="baidu"),
        )
    else:
        providers = _CountingProviders(DefaultMarketProviders())

    app = create_app(
        service=_StubJobs(),
        server_config=ServerConfig(),
        report_store=ReportStore(temp / "reports"),
        ticker_directory=TickerDirectory({TICKER: TICKER_NAME}, clock=clock),
        export_service=_StubExports(),
        market_providers=providers,
    )
    client = TestClient(app)
    # create_app keeps its own cache: an empty MarketCache is falsy because it
    # defines __len__, so an injected one would be replaced anyway.
    return client, providers, app.state.market_cache


def _result(
    args: argparse.Namespace,
    warm: list[float],
    cold: list[float],
    providers: Any,
) -> dict[str, Any]:
    warm_p95 = _nearest_rank_p95(warm)
    cold_p95 = _nearest_rank_p95(cold)
    calls = getattr(providers, "calls", None)
    provider_calls = dict(calls) if isinstance(calls, Counter) else {}
    conclusion = (
        "pass"
        if warm_p95 <= WARM_LINE_MS and cold_p95 <= COLD_LINE_MS
        else "fail"
    )
    return {
        "ticket": "P4-12",
        "mode": args.mode,
        "measured_at": datetime.now(CST).isoformat(timespec="seconds"),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "backend": "TestClient(create_app) in-process",
        },
        "dataset": {
            "ticker": args.ticker,
            "payload_source": (
                "tests/backend/stock_helpers.py"
                if args.mode == "fixture"
                else "DefaultMarketProviders（真实供应商）"
            ),
            "blocks": ["quote", "valuation", "sector_blocks"],
        },
        "samples": {"warmups": args.warmups, "measured": args.samples},
        "snapshot_warm": {
            "median_ms": round(statistics.median(warm), 2),
            "p95_ms": round(warm_p95, 2),
            "hard_line_ms": WARM_LINE_MS,
            "pass": warm_p95 <= WARM_LINE_MS,
        },
        "snapshot_cold": {
            "median_ms": round(statistics.median(cold), 2),
            "p95_ms": round(cold_p95, 2),
            "hard_line_ms": COLD_LINE_MS,
            "pass": cold_p95 <= COLD_LINE_MS,
        },
        "provider_calls": provider_calls,
        "external_network_calls": (
            0
            if args.mode == "fixture"
            else int(sum(provider_calls.values()))
        ),
        "conclusion": conclusion,
        "command": (
            ".venv/Scripts/python.exe scripts/p4_market_perf.py "
            f"--{args.mode} --ticker {args.ticker} --samples {args.samples}"
        ),
        "note": (
            "fixture 模式只验采样、分位与阈值逻辑，数值不代表供应商时延；"
            "真实门槛以 --live 的 30 样本为准。"
            if args.mode == "fixture"
            else "live 模式每次冷样本清空 MarketCache，三个块都会打到真实供应商。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", dest="mode", action="store_const", const="fixture")
    mode.add_argument("--live", dest="mode", action="store_const", const="live")
    parser.add_argument("--ticker", default=TICKER)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.samples < 30:
        parser.error("--samples must be at least 30")

    url = f"/api/v1/stocks/{args.ticker}/snapshot"
    with tempfile.TemporaryDirectory() as raw:
        client, providers, cache = _build_client(args.mode, Path(raw))
        try:
            warm = _measure(
                client, url, warmups=args.warmups, samples=args.samples
            )
            cold = _measure_cold(client, cache, url, samples=args.samples)
        finally:
            client.close()

    result = _result(args, warm, cold, providers)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["conclusion"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
