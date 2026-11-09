"""Market envelope builder (``market-data-envelope-v1``).

One place turns block outcomes into the frozen envelope. Providers never build
envelopes; services hand their per-block results here so the four mutually
exclusive states, the ``partial`` modifier and the merge table from
``api-v1.md`` 3.0 are enforced once.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "market-envelope-v1"

STATUSES = ("ok", "empty", "error", "stale")
USABLE_STATUSES = ("ok", "stale")
FAILED_STATUSES = ("empty", "error")

SOURCES = frozenset(
    {
        "tencent",
        "eastmoney",
        "ths",
        "hexin",
        "cls",
        "mootdx",
        "mootdx-cache",
        "baidu",
        "mixed",
        "static",
    }
)

STALE_REASONS = ("ttl_exceeded", "trading_day_mismatch", "upstream_fallback")

ERROR_MESSAGES = {
    "upstream_timeout": "数据服务响应超时",
    "upstream_error": "数据服务暂时不可用",
    "upstream_rate_limited": "数据源请求过于频繁，请稍后再试",
    "data_parse_error": "数据源返回内容无法解析",
}


class EnvelopeError(ValueError):
    """A caller tried to build an envelope the frozen schema rejects."""


@dataclass(frozen=True)
class BlockResult:
    """One block's outcome before it becomes a ``blocks`` entry."""

    status: str
    source: str
    as_of: str | None
    fetched_at: str
    data: Any = None
    stale_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_doc(self) -> dict[str, Any]:
        _check_block(self)
        return {
            "status": self.status,
            "source": self.source,
            "as_of": self.as_of,
            "fetched_at": self.fetched_at,
            "is_stale": self.status == "stale",
            "stale_reason": self.stale_reason,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


def build_envelope(
    *,
    status: str,
    source: str,
    as_of: str | None,
    fetched_at: str,
    data: Any,
    stale_reason: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    blocks: Mapping[str, BlockResult] | None = None,
    partial: bool = False,
    failed_blocks: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Build and validate a single document.

    Multi-block callers should normally use :func:`build_blocks_envelope`,
    which derives status/partial/failed_blocks from the blocks themselves.
    """
    if status not in STATUSES:
        raise EnvelopeError(f"未知 status: {status}")
    if source not in SOURCES:
        raise EnvelopeError(f"未知 source: {source}")
    if status == "error" and not error_code:
        raise EnvelopeError("error 状态必须给 error_code")
    if status == "error" and not error_message:
        error_message = ERROR_MESSAGES.get(error_code, ERROR_MESSAGES["upstream_error"])
    doc = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source": source,
        "as_of": as_of,
        "fetched_at": fetched_at,
        "is_stale": status == "stale",
        "stale_reason": stale_reason,
        "error_code": error_code,
        "error_message": error_message,
        "partial": bool(partial),
        "failed_blocks": list(failed_blocks),
        "data": data,
    }
    if blocks is not None:
        doc["blocks"] = {name: block.to_doc() for name, block in blocks.items()}
    validate_envelope(doc)
    return doc


def build_blocks_envelope(
    blocks: Mapping[str, BlockResult],
    *,
    extra_data: Mapping[str, Any] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Merge block outcomes using the five-row table in ``api-v1.md`` 3.0."""
    if not blocks:
        raise EnvelopeError("多块信封至少需要一个块")
    for block in blocks.values():
        _check_block(block)

    usable = [(name, block) for name, block in blocks.items() if block.status in USABLE_STATUSES]
    failed = [name for name, block in blocks.items() if block.status in FAILED_STATUSES]
    fetched = fetched_at or _latest_fetched_at(blocks)

    if not usable:
        if all(block.status == "empty" for block in blocks.values()):
            return build_envelope(
                status="empty",
                source=_aggregate_source(blocks),
                as_of=None,
                fetched_at=fetched,
                data=None,
                blocks=blocks,
            )
        first_error = next(
            block for block in blocks.values() if block.status == "error"
        )
        return build_envelope(
            status="error",
            source=_aggregate_source(blocks),
            as_of=None,
            fetched_at=fetched,
            data=None,
            error_code=first_error.error_code,
            error_message=first_error.error_message,
            blocks=blocks,
        )

    status = "stale" if any(block.status == "stale" for _, block in usable) else "ok"
    partial = bool(failed)
    parent_name, parent = _primary_block(blocks, usable)
    stale_reason = None
    if status == "stale":
        if parent.status == "stale":
            stale_reason = parent.stale_reason
        else:
            stale_reason = next(
                block.stale_reason for _, block in usable if block.status == "stale"
            )

    merged: dict[str, Any] = {}
    for name, block in blocks.items():
        merged[name] = block.data if block.status in USABLE_STATUSES else None
    if extra_data:
        merged.update(extra_data)

    return build_envelope(
        status=status,
        source=_aggregate_source(blocks),
        as_of=parent.as_of,
        fetched_at=fetched,
        data=merged,
        stale_reason=stale_reason,
        blocks=blocks,
        partial=partial,
        failed_blocks=tuple(failed) if partial else (),
    )


def validate_envelope(doc: Mapping[str, Any]) -> None:
    """Enforce the parts of the frozen schema the builder is responsible for."""
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise EnvelopeError("schema_version 必须是 market-envelope-v1")
    status = doc.get("status")
    if status not in STATUSES:
        raise EnvelopeError(f"未知 status: {status}")
    if doc.get("source") not in SOURCES:
        raise EnvelopeError(f"未知 source: {doc.get('source')}")
    fetched_at = doc.get("fetched_at")
    if not isinstance(fetched_at, str) or len(fetched_at) < 10:
        raise EnvelopeError("fetched_at 必须是非空 ISO 时间")
    if doc.get("is_stale") is not (status == "stale"):
        raise EnvelopeError("is_stale 必须恒等于 status == stale")

    data = doc.get("data")
    as_of = doc.get("as_of")
    if status in ("empty", "error"):
        if data is not None:
            raise EnvelopeError(f"{status} 状态 data 必须为 null")
        if as_of is not None:
            raise EnvelopeError(f"{status} 状态 as_of 必须为 null")
    else:
        if data is None:
            raise EnvelopeError(f"{status} 状态 data 必须非 null")
        if not isinstance(as_of, str) or not as_of:
            raise EnvelopeError(f"{status} 状态 as_of 必须非空")

    if status == "error":
        if not doc.get("error_code"):
            raise EnvelopeError("error 状态必须给 error_code")
        if not doc.get("error_message"):
            raise EnvelopeError("error 状态必须给 error_message")
        if doc.get("stale_reason") is not None:
            raise EnvelopeError("error 状态 stale_reason 必须为 null")
    elif status == "empty":
        if doc.get("error_code") or doc.get("error_message"):
            raise EnvelopeError("empty 状态不得带错误码")
        if doc.get("stale_reason") is not None:
            raise EnvelopeError("empty 状态 stale_reason 必须为 null")
    elif status == "ok":
        if doc.get("error_code") or doc.get("error_message"):
            raise EnvelopeError("ok 状态不得带错误码")
        if doc.get("stale_reason") is not None:
            raise EnvelopeError("ok 状态 stale_reason 必须为 null")
    else:
        if doc.get("stale_reason") not in STALE_REASONS:
            raise EnvelopeError("stale 状态必须给合法 stale_reason")
        if doc.get("error_code") or doc.get("error_message"):
            raise EnvelopeError("stale 状态不得带错误码")

    partial = bool(doc.get("partial"))
    failed_blocks = doc.get("failed_blocks")
    if not isinstance(failed_blocks, list):
        raise EnvelopeError("failed_blocks 必须是数组")
    if partial and not failed_blocks:
        raise EnvelopeError("partial=true 时 failed_blocks 必须非空")
    if not partial and failed_blocks:
        raise EnvelopeError("partial=false 时 failed_blocks 必须为空")

    blocks = doc.get("blocks")
    if blocks is not None:
        if not isinstance(blocks, Mapping) or not blocks:
            raise EnvelopeError("blocks 必须是非空对象")
        for name, block in blocks.items():
            if not isinstance(block, Mapping):
                raise EnvelopeError(f"块 {name} 必须是对象")
            _check_block_doc(name, block)


def _check_block(block: BlockResult) -> None:
    _check_block_doc(
        "block",
        {
            "status": block.status,
            "source": block.source,
            "as_of": block.as_of,
            "fetched_at": block.fetched_at,
            "is_stale": block.status == "stale",
            "stale_reason": block.stale_reason,
            "error_code": block.error_code,
            "error_message": block.error_message,
        },
    )


def _check_block_doc(name: str, block: Mapping[str, Any]) -> None:
    status = block.get("status")
    if status not in STATUSES:
        raise EnvelopeError(f"{name}: 未知 status: {status}")
    if block.get("source") not in SOURCES:
        raise EnvelopeError(f"{name}: 未知 source: {block.get('source')}")
    if not isinstance(block.get("fetched_at"), str) or len(block["fetched_at"]) < 10:
        raise EnvelopeError(f"{name}: fetched_at 非法")
    if block.get("is_stale") is not (status == "stale"):
        raise EnvelopeError(f"{name}: is_stale 必须恒等于 status == stale")
    as_of = block.get("as_of")
    if status in USABLE_STATUSES:
        if not isinstance(as_of, str) or not as_of:
            raise EnvelopeError(f"{name}: {status} 状态 as_of 必须非空")
    elif as_of is not None:
        raise EnvelopeError(f"{name}: {status} 状态 as_of 必须为 null")

    if status == "error":
        if not block.get("error_code") or not block.get("error_message"):
            raise EnvelopeError(f"{name}: error 状态必须给 error_code 与 error_message")
        if block.get("stale_reason") is not None:
            raise EnvelopeError(f"{name}: error 状态 stale_reason 必须为 null")
    else:
        if block.get("error_code") or block.get("error_message"):
            raise EnvelopeError(f"{name}: {status} 状态不得带错误码")
        if status == "stale":
            if block.get("stale_reason") not in STALE_REASONS:
                raise EnvelopeError(f"{name}: stale 状态 stale_reason 非法")
        elif block.get("stale_reason") is not None:
            raise EnvelopeError(f"{name}: {status} 状态 stale_reason 必须为 null")


def _aggregate_source(blocks: Mapping[str, BlockResult]) -> str:
    sources = {block.source for block in blocks.values()}
    if len(sources) == 1:
        return next(iter(sources))
    return "mixed"


def _primary_block(
    blocks: Mapping[str, BlockResult],
    usable: list[tuple[str, BlockResult]],
) -> tuple[str, BlockResult]:
    """First declared usable block: quote for snapshots, indices for overview."""
    for name in blocks:
        if blocks[name].status in USABLE_STATUSES:
            return name, blocks[name]
    return usable[0]


def _latest_fetched_at(blocks: Mapping[str, BlockResult]) -> str:
    return max(block.fetched_at for block in blocks.values())
