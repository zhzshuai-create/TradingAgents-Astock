"""Chart input snapshots for new reports (RPT-01).

A snapshot is file evidence, not a contract: the worker writes it to
``<job>/chart_snapshot.json`` before the terminal transaction and marks the
report ``frozen`` only when that write succeeded. Everything here is therefore
allowed to fail; the caller downgrades to ``none`` and the run still succeeds.

Status rule (RPT-01 D3): ``frozen`` iff both blocks are usable (``ok`` or
``stale``) and carry data; otherwise ``none`` with the first failing reason.
``stale`` still freezes because the chart wants the data as it was seen, and a
stale block keeps its ``as_of``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

from backend.app.services.market_envelope import USABLE_STATUSES
from backend.app.services.market_clock import format_cst, now_cst
from backend.app.services.stock_service import StockService

CHART_SNAPSHOT_VERSION = "chart-snapshot-v1"
MAX_CHART_SNAPSHOT_BYTES = 512 * 1024
BLOCK_NAMES = ("quote", "kline")


class ChartSnapshotOversize(ValueError):
    """The document exceeds ``MAX_CHART_SNAPSHOT_BYTES`` and is discarded."""


class ChartSnapshotter(Protocol):
    def capture(self, ticker: str, *, content_hash: str) -> dict[str, Any]: ...


class MarketChartSnapshotter:
    def __init__(
        self,
        stock: StockService,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._stock = stock
        self._clock = clock or now_cst

    def capture(self, ticker: str, *, content_hash: str) -> dict[str, Any]:
        envelope = self._stock.chart_inputs(ticker)
        metas = envelope.get("blocks") or {}
        merged = envelope.get("data") or {}
        blocks = {
            name: _block(metas.get(name), merged.get(name)) for name in BLOCK_NAMES
        }
        reason = _failure_reason(blocks)
        payload = {
            "schema_version": CHART_SNAPSHOT_VERSION,
            "ticker": ticker,
            "captured_at": format_cst(self._clock()),
            "report_content_hash": content_hash,
            "status": "frozen" if reason is None else "none",
            "reason": reason,
            "blocks": blocks,
        }
        size = len(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        if size > MAX_CHART_SNAPSHOT_BYTES:
            raise ChartSnapshotOversize(f"oversize: {size} bytes")
        return payload


def _block(meta: Any, data: Any) -> dict[str, Any]:
    meta = meta if isinstance(meta, Mapping) else {}
    return {
        "status": meta.get("status"),
        "source": meta.get("source"),
        "as_of": meta.get("as_of"),
        "fetched_at": meta.get("fetched_at"),
        "data": data,
    }


def _failure_reason(blocks: Mapping[str, dict[str, Any]]) -> str | None:
    for name in BLOCK_NAMES:
        block = blocks[name]
        status = block["status"]
        if status == "error":
            return f"{name}_error"
        if status not in USABLE_STATUSES:
            return f"{name}_empty" if status == "empty" else f"{name}_error"
        if not _has_data(name, block["data"]):
            return f"{name}_empty"
    return None


def _has_data(name: str, data: Any) -> bool:
    if name == "kline" and isinstance(data, Mapping):
        return bool(data.get("bars"))
    if isinstance(data, (Mapping, list, tuple, str)):
        return bool(data)
    return data is not None
