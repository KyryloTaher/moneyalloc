"""Data models for the Money Allocation application."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_TIME_HORIZON_ALIASES: dict[str, str] = {
    "y": "Y",
    "yr": "Y",
    "yrs": "Y",
    "year": "Y",
    "years": "Y",
    "m": "M",
    "mo": "M",
    "mos": "M",
    "month": "M",
    "months": "M",
    "w": "W",
    "wk": "W",
    "wks": "W",
    "week": "W",
    "weeks": "W",
    "d": "D",
    "day": "D",
    "days": "D",
}

_CANONICAL_HORIZON_PATTERN = re.compile(r"^(\d+)\s*([ymwd])$", re.IGNORECASE)
_TEXTUAL_HORIZON_PATTERN = re.compile(r"^(\d+)\s*([a-z]+)$", re.IGNORECASE)

MAX_TIME_HORIZON_LABEL = "Max"
CASH_TIME_HORIZON_LABEL = "Cash"
NONE_TIME_HORIZON_LABEL = "Cash-like"


def canonicalize_time_horizon(value: Optional[str]) -> Optional[str]:
    """Return the canonical representation of a time horizon.

    The canonical format uses an integer followed by an upper-case unit letter:
    ``Y`` for years, ``M`` for months, ``W`` for weeks and ``D`` for days. The
    function accepts common textual variations such as ``"1 year"`` or
    ``"6 months"`` and converts them to ``"1Y"`` or ``"6M"`` respectively. When
    the value is empty ``None`` is returned. A :class:`ValueError` is raised for
    unrecognised formats.
    """

    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered == MAX_TIME_HORIZON_LABEL.lower():
        return MAX_TIME_HORIZON_LABEL
    if lowered == NONE_TIME_HORIZON_LABEL.lower():
        return NONE_TIME_HORIZON_LABEL

    canonical_match = _CANONICAL_HORIZON_PATTERN.fullmatch(text)
    if canonical_match:
        number, unit = canonical_match.groups()
        numeric = int(number)
        if numeric <= 0:
            raise ValueError(f"Time horizon must be positive: {value!r}")
        return f"{numeric}{unit.upper()}"

    textual_match = _TEXTUAL_HORIZON_PATTERN.fullmatch(text)
    if textual_match:
        number, unit_text = textual_match.groups()
        numeric = int(number)
        if numeric <= 0:
            raise ValueError(f"Time horizon must be positive: {value!r}")
        mapped_unit = _TIME_HORIZON_ALIASES.get(unit_text.lower())
        if mapped_unit:
            return f"{numeric}{mapped_unit}"

    raise ValueError(f"Invalid time horizon value: {value!r}")


def display_time_horizon(value: Optional[str]) -> str:
    """Return a display-friendly time horizon string."""

    if value is None:
        return ""
    try:
        canonical = canonicalize_time_horizon(value)
    except ValueError:
        return value.strip()
    return canonical or ""


@dataclass(slots=True)
class Allocation:
    """Represents a single allocation node in the hierarchy."""

    id: Optional[int]
    parent_id: Optional[int]
    name: str
    currency: Optional[str]
    instrument: Optional[str]
    target_percent: float
    include_in_rollup: bool
    notes: str
    sort_order: int = 0
    current_value: float = 0.0
    time_horizon: Optional[str] = None

    @property
    def normalized_currency(self) -> str:
        """Return the currency string suitable for display."""
        return (self.currency or "").strip()

    @property
    def normalized_instrument(self) -> str:
        """Return the instrument string suitable for display."""
        return (self.instrument or "").strip()

    @property
    def normalized_time_horizon(self) -> str:
        """Return the time horizon string suitable for display."""
        return display_time_horizon(self.time_horizon)


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


@dataclass(slots=True)
class DistributionRiskInput:
    """Stores risk input values captured alongside a distribution."""

    id: Optional[int]
    distribution_id: int
    currency: str
    time_horizon: str
    sleeve: str
    yield_value: Optional[float]
    tenor_value: Optional[float]


__all__ = [
    "Allocation",
    "Distribution",
    "DistributionEntry",
    "DistributionRiskInput",
    "canonicalize_time_horizon",
    "display_time_horizon",
    "MAX_TIME_HORIZON_LABEL",
    "NONE_TIME_HORIZON_LABEL",
]
