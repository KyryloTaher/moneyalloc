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
    current_value: float = 0.0

    @property
    def normalized_currency(self) -> str:
        """Return the currency string suitable for display."""
        return (self.currency or "").strip()


@dataclass(slots=True)
class Distribution:
    """Represents a recorded distribution event."""

    id: Optional[int]
    name: str
    total_amount: float
    tolerance_percent: float
    created_at: str


@dataclass(slots=True)
class DistributionEntry:
    """Stores a single recommendation entry inside a distribution."""

    id: Optional[int]
    distribution_id: int
    allocation_id: int
    allocation_path: str
    currency: str
    target_share: float
    current_value: float
    current_share: float
    target_value: float
    recommended_change: float
    share_diff: float
    action: str


__all__ = ["Allocation", "Distribution", "DistributionEntry"]
