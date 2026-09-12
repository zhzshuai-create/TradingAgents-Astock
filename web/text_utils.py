"""Shared text-cleaning helpers for the web layer."""

from __future__ import annotations

import re


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks (and trailing whitespace) from LLM output."""
    return re.sub(r"<think>.*?</think>\s*", "", text or "", flags=re.DOTALL).strip()
