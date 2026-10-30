"""Resolve the contract's ticker input to a 6-digit A-stock code.

Codes and exchange prefixes/suffixes are handled locally so the common path
never touches the network. Chinese names use the platform's cached market map,
imported lazily: backend tests and code-only requests must not load it.
"""

from __future__ import annotations

import re

_CODE = re.compile(r"^[0-9]{6}$")
_SUFFIXES = (".SH", ".SZ", ".BJ")
_PREFIXES = ("SH", "SZ", "BJ")


class TickerUnresolved(ValueError):
    pass


class TickerAmbiguous(ValueError):
    def __init__(self, candidates: list[dict[str, str]]) -> None:
        super().__init__("ticker matches more than one stock")
        self.candidates = candidates


def resolve_ticker(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise TickerUnresolved(raw)

    code = _strip_exchange(raw)
    if _CODE.match(code):
        return code
    if not _has_chinese(raw):
        raise TickerUnresolved(raw)
    return _resolve_name(raw)


def _strip_exchange(raw: str) -> str:
    text = raw.strip().upper()
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text


def _has_chinese(raw: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in raw)


def _resolve_name(raw: str) -> str:
    from tradingagents.dataflows.a_stock import _common

    name_to_code, _ = _common._build_name_code_map()
    clean = raw.replace(" ", "").replace("\u3000", "")
    if clean in name_to_code:
        return name_to_code[clean]

    matches = [(name, code) for name, code in name_to_code.items() if clean in name]
    if len(matches) == 1:
        return matches[0][1]
    if len(matches) > 1:
        raise TickerAmbiguous(
            [{"code": code, "name": name} for name, code in matches[:5]]
        )
    raise TickerUnresolved(raw)
