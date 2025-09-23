"""Utilities for parsing and formatting time horizon labels."""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional

__all__ = [
    "normalize_time_horizon",
    "try_normalize_time_horizon",
    "display_time_horizon",
    "merge_time_horizons",
]

_VALID_PATTERN = re.compile(r"^(?P<value>\d+)\s*(?P<unit>[YMWD])$", re.IGNORECASE)
_UNIT_TO_DAYS = {"D": 1, "W": 7, "M": 30, "Y": 365}


def normalize_time_horizon(value: Optional[str]) -> Optional[str]:
    """Return a canonical representation of a time horizon.

    Accepts labels expressed as ``<number><unit>`` or ``<number> <unit>`` where the
    unit is one of ``Y`` (years), ``M`` (months), ``W`` (weeks) or ``D`` (days).
    The number must be strictly positive. The function raises :class:`ValueError`
    when the input does not comply with the expected format.
    """

    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    match = _VALID_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(
            "Time horizon must be expressed as '<number><unit>' (e.g. 6M, 3Y) "
            "using Y, M, W or D as the unit."
        )
    amount = int(match.group("value"))
    if amount <= 0:
        raise ValueError("Time horizon value must be greater than zero.")
    unit = match.group("unit").upper()
    return f"{amount}{unit}"


def try_normalize_time_horizon(value: Optional[str]) -> Optional[str]:
    """Best-effort normalisation that returns ``None`` for invalid values."""

    try:
        return normalize_time_horizon(value)
    except ValueError:
        return None


def display_time_horizon(value: Optional[str]) -> str:
    """Return a user-facing representation of a stored horizon value."""

    if value is None:
        return ""
    text = value.strip()
    if not text:
        return ""
    normalized = try_normalize_time_horizon(text)
    return normalized if normalized is not None else text


def _sort_key(value: str) -> tuple[float, str]:
    normalized = try_normalize_time_horizon(value)
    if normalized is None:
        return (math.inf, value.lower())
    amount = int(normalized[:-1])
    unit = normalized[-1]
    multiplier = _UNIT_TO_DAYS[unit]
    return (amount * multiplier, normalized.lower())


def merge_time_horizons(
    values: Iterable[Optional[str]], defaults: Iterable[str] = ()
) -> list[str]:
    """Combine existing and default horizons into a sorted, de-duplicated list."""

    collected: set[str] = set()
    for candidate in defaults:
        normalized = try_normalize_time_horizon(candidate)
        if normalized:
            collected.add(normalized)
    for value in values:
        normalized = try_normalize_time_horizon(value)
        if normalized:
            collected.add(normalized)
    return sorted(collected, key=_sort_key)
