"""Data models for the Money Allocation application."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class Allocation:
    """Represents a single allocation node in the hierarchy."""

    id: Optional[int]
    parent_id: Optional[int]
    name: str
    currency: Optional[str]
    target_percent: float
    include_in_rollup: bool
    notes: str
    sort_order: int = 0

    @property
    def normalized_currency(self) -> str:
        """Return the currency string suitable for display."""
        return (self.currency or "").strip()


__all__ = ["Allocation"]
