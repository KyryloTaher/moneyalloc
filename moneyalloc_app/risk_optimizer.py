"""Risk-aware distribution optimisation utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


Bucket = str
Sleeve = str  # "rates", "tips" or "credit"


@dataclass(slots=True)
class ProblemSpec:
    """Input specification for the risk optimisation routine."""

    bucket_weights: Dict[Bucket, float]
    bucket_horizons: Dict[Bucket, float]
    tenors: Dict[Tuple[Bucket, Sleeve], float]


@dataclass(slots=True)
class RiskOptimizationResult:
    """Container describing the optimised allocations."""

    allocations: Dict[Tuple[Bucket, Sleeve], float]
    by_bucket: Dict[Bucket, float]
    by_sleeve: Dict[Sleeve, float]


_FLOAT_TOLERANCE = 1e-9


def _normalise_weights(values: Dict[Bucket, float]) -> Dict[Bucket, float]:
    """Return weights normalised to sum to one."""

    positive = {bucket: float(weight) for bucket, weight in values.items() if weight > 0.0}
    if not positive:
        raise ValueError("At least one positive bucket weight is required for optimisation.")

    total = sum(positive.values())
    if total <= 0.0:
        raise ValueError("Bucket weights must sum to a positive value.")

    return {bucket: weight / total for bucket, weight in positive.items()}


def _sorted_buckets(weights: Dict[Bucket, float], horizons: Dict[Bucket, float]) -> Iterable[Bucket]:
    """Return bucket identifiers sorted by ascending horizon then name."""

    missing = [bucket for bucket in weights if bucket not in horizons]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Missing horizon information for: {missing_list}")

    return sorted(weights, key=lambda bucket: (horizons[bucket], bucket))


def _tenors_for_bucket(
    bucket: Bucket,
    *,
    horizons: Dict[Bucket, float],
    tenors: Dict[Tuple[Bucket, Sleeve], float],
    previous: Dict[Sleeve, float],
) -> Dict[Sleeve, float]:
    """Return sleeves available for the provided bucket."""

    bucket_horizon = horizons[bucket]
    available: Dict[Sleeve, float] = {}

    for (source_bucket, sleeve), tenor in tenors.items():
        if tenor is None:
            continue
        tenor_value = float(tenor)
        if tenor_value <= 0.0:
            continue
        source_horizon = horizons.get(source_bucket)
        if source_horizon is None:
            continue
        if source_horizon - bucket_horizon > _FLOAT_TOLERANCE:
            continue
        if tenor_value - bucket_horizon > _FLOAT_TOLERANCE:
            continue
        existing = available.get(sleeve)
        if existing is None or tenor_value < existing:
            available[sleeve] = tenor_value

    # Ensure sleeves from previous stages remain available even if no new
    # tenor is supplied for the current bucket.
    for sleeve, tenor in previous.items():
        available.setdefault(sleeve, tenor)

    if not available:
        raise ValueError(f"No sleeves with tenor <= horizon found for bucket {bucket}.")

    return available


def _distribute_remaining(
    allocations: Dict[Sleeve, float],
    remaining: float,
    sleeves: Dict[Sleeve, float],
) -> None:
    """Distribute the remaining allocation using inverse-tenor weights."""

    if remaining <= _FLOAT_TOLERANCE:
        return

    inverse_weights = {sleeve: 1.0 / tenor for sleeve, tenor in sleeves.items() if tenor > 0.0}
    weight_total = sum(inverse_weights.values())
    if weight_total <= 0.0:
        raise ValueError("Unable to determine sleeve weights for optimisation.")

    running_total = 0.0
    ordered = sorted(sleeves.items(), key=lambda item: (item[1], item[0]))
    for sleeve, tenor in ordered[:-1]:
        share = inverse_weights[sleeve] / weight_total
        addition = remaining * share
        allocations[sleeve] = allocations.get(sleeve, 0.0) + addition
        running_total += addition

    # Assign any residual amount to the sleeve with the lowest tenor to keep
    # totals consistent and bias towards lower duration risk.
    last_sleeve = ordered[-1][0]
    residual = remaining - running_total
    allocations[last_sleeve] = allocations.get(last_sleeve, 0.0) + residual


def run_risk_equal_optimization(spec: ProblemSpec) -> RiskOptimizationResult:
    """Optimise allocations using a cascading risk-aware algorithm."""

    normalised = _normalise_weights(spec.bucket_weights)
    ordered_buckets = tuple(_sorted_buckets(normalised, spec.bucket_horizons))

    cumulative_targets: Dict[Bucket, float] = {}
    running_total = 0.0
    for bucket in ordered_buckets:
        running_total += normalised[bucket]
        cumulative_targets[bucket] = running_total

    previous_sleeves: Dict[Sleeve, float] = {}
    cumulative_allocations: Dict[Bucket, Dict[Sleeve, float]] = {}

    for bucket in ordered_buckets:
        sleeves = _tenors_for_bucket(
            bucket,
            horizons=spec.bucket_horizons,
            tenors=spec.tenors,
            previous=previous_sleeves,
        )
        target_total = cumulative_targets[bucket]
        allocations = {sleeve: previous_sleeves.get(sleeve, 0.0) for sleeve in sleeves}
        already_assigned = sum(allocations.values())

        if already_assigned - target_total > _FLOAT_TOLERANCE:
            raise ValueError(
                "Cumulative bucket weights must be non-decreasing with respect to time horizon."
            )

        remaining = target_total - already_assigned
        _distribute_remaining(allocations, remaining, sleeves)

        cumulative_allocations[bucket] = allocations
        previous_sleeves = dict(allocations)

    allocations: Dict[Tuple[Bucket, Sleeve], float] = {}
    by_bucket: Dict[Bucket, float] = {}
    by_sleeve: Dict[Sleeve, float] = {}

    previous_totals: Dict[Sleeve, float] = {}
    for bucket in ordered_buckets:
        current = cumulative_allocations[bucket]
        bucket_total = 0.0
        for sleeve, value in current.items():
            previous_value = previous_totals.get(sleeve, 0.0)
            increment = value - previous_value
            if increment < -_FLOAT_TOLERANCE:
                raise ValueError("Computed negative allocation increment; check inputs for consistency.")
            if increment < 0.0:
                increment = 0.0
            allocations[(bucket, sleeve)] = increment
            bucket_total += increment
            by_sleeve[sleeve] = by_sleeve.get(sleeve, 0.0) + increment
        by_bucket[bucket] = bucket_total
        previous_totals = current

    total_allocated = sum(by_bucket.values())
    if total_allocated <= 0.0:
        raise ValueError("Optimisation produced zero allocation. Check bucket weights and tenors.")

    # Normalise the outputs so the total sums to one.
    allocations = {
        key: value / total_allocated
        for key, value in allocations.items()
        if value > _FLOAT_TOLERANCE
    }
    by_bucket = {
        bucket: value / total_allocated
        for bucket, value in by_bucket.items()
        if value > _FLOAT_TOLERANCE
    }
    by_sleeve = {
        sleeve: value / total_allocated
        for sleeve, value in by_sleeve.items()
        if value > _FLOAT_TOLERANCE
    }

    return RiskOptimizationResult(
        allocations=allocations,
        by_bucket=by_bucket,
        by_sleeve=by_sleeve,
    )


__all__ = [
    "ProblemSpec",
    "RiskOptimizationResult",
    "run_risk_equal_optimization",
]

