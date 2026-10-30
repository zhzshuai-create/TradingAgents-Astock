"""Declarative base and shared constraint helpers for the job kernel."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def sql_in(column: str, values: Iterable[str]) -> str:
    """Render a CHECK fragment from a fixed, in-code literal tuple."""
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"
