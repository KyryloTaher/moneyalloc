"""Core allocation and calculation utilities."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .database import AllocationRecord, BucketRecord, ResultRecord


@dataclass
class LeafAllocation:
    bucket_key: str
    time_horizon: float
    currency: str
    percentage: float


@dataclass
class Recommendation:
    action: str
    risk_group: str
    currency: str
    tenor: float
    amount: float


def normalise_percentage(value: float) -> float:
    """Return a percentage in the range [0, 100]."""
    return max(0.0, min(100.0, value))


def build_leaf_allocations(allocations: Iterable[AllocationRecord]) -> List[LeafAllocation]:
    """Build leaf allocations from a collection of allocation records."""

    by_parent: Dict[int | None, List[AllocationRecord]] = {}
    lookup: Dict[int, AllocationRecord] = {}
    for allocation in allocations:
        lookup[allocation.id] = allocation
        by_parent.setdefault(allocation.parent_id, []).append(allocation)

    leaves: List[LeafAllocation] = []

    def traverse(node: AllocationRecord, cumulative: float) -> None:
        current = cumulative * (node.percentage / 100.0)
        children = by_parent.get(node.id, [])
        if node.is_leaf or not children:
            if not node.currencies:
                return
            currencies = [c.strip() for c in node.currencies.split(",") if c.strip()]
            if not currencies:
                return
            if node.time_horizon is None:
                return
            currency_share = current * 100.0 / len(currencies)
            for currency in currencies:
                bucket_key = f"{node.time_horizon}|{currency.upper()}"
                leaves.append(
                    LeafAllocation(
                        bucket_key=bucket_key,
                        time_horizon=node.time_horizon,
                        currency=currency.upper(),
                        percentage=currency_share,
                    )
                )
        else:
            for child in children:
                traverse(child, current)

    for root in by_parent.get(None, []):
        traverse(root, 1.0)

    return leaves


def build_bucket_records(leaves: Sequence[LeafAllocation]) -> List[BucketRecord]:
    buckets: Dict[str, BucketRecord] = {}
    for leaf in leaves:
        bucket = buckets.get(leaf.bucket_key)
        if bucket:
            bucket.percentage += leaf.percentage
        else:
            buckets[leaf.bucket_key] = BucketRecord(
                bucket_key=leaf.bucket_key,
                time_horizon=leaf.time_horizon,
                currency=leaf.currency,
                percentage=leaf.percentage,
            )
    return list(buckets.values())


def parse_tenor_string(value: str) -> List[float]:
    tenors: List[float] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            tenors.append(float(item))
        except ValueError:
            continue
    return tenors


def _calc_dv01_combination(
    bucket_keys: Sequence[str],
    options: Sequence[List[Tuple[float, float]]],
) -> Tuple[List[float], float, float]:
    """Try all tenor combinations to minimise spread and variance."""

    combination_count = math.prod(len(o) for o in options) if options else 0
    if combination_count == 0:
        return [], float("inf"), float("inf")

    best_tenors: List[float] = []
    best_spread = float("inf")
    best_variance = float("inf")

    if combination_count <= 50000:
        for candidate in itertools.product(*options):
            tenors = [c[0] for c in candidate]
            exposures = [c[1] for c in candidate]
            spread = max(exposures) - min(exposures)
            variance = pstdev(exposures)
            if spread < best_spread or (math.isclose(spread, best_spread) and variance < best_variance):
                best_spread = spread
                best_variance = variance
                best_tenors = tenors
    else:
        # Greedy approximation: aim for the mean of mid-range exposures.
        midpoint = mean([(min(o, key=lambda x: x[1])[1] + max(o, key=lambda x: x[1])[1]) / 2 for o in options])
        best_tenors = []
        best_spread = float("inf")
        exposures: List[float] = []
        for choices in options:
            tenor, exposure = min(choices, key=lambda x: abs(x[1] - midpoint))
            best_tenors.append(tenor)
            exposures.append(exposure)
        best_spread = max(exposures) - min(exposures)
        best_variance = pstdev(exposures) if len(exposures) > 1 else 0.0

    return best_tenors, best_spread, best_variance


def calculate_results(
    buckets: Sequence[BucketRecord],
    tenor_inputs: Dict[str, Dict[str, List[float]]],
    total_amount: float,
) -> List[ResultRecord]:
    """Calculate risk-balanced allocations."""

    if not buckets:
        return []

    bucket_keys = [bucket.bucket_key for bucket in buckets]
    amounts = []
    options: List[List[Tuple[float, float]]] = []
    group_availability: Dict[str, set[str]] = {}

    for bucket in buckets:
        bucket_amount = total_amount * (bucket.percentage / 100.0)
        amounts.append(bucket_amount)
        bucket_tenors = tenor_inputs.get(bucket.bucket_key, {})
        dv01_tenors = [
            t for t in bucket_tenors.get("DV01", []) if t <= bucket.time_horizon + 1e-9
        ]
        if not dv01_tenors:
            # Default to min(time_horizon, 1) if no valid tenor provided
            fallback = min(bucket.time_horizon, 1.0)
            dv01_tenors = [fallback]
        options.append([(tenor, bucket_amount * tenor) for tenor in dv01_tenors])

        available_groups = {"DV01"}
        bei01_tenors = [
            t for t in bucket_tenors.get("BEI01", []) if t <= bucket.time_horizon + 1e-9
        ]
        cs01_tenors = [
            t for t in bucket_tenors.get("CS01", []) if t <= bucket.time_horizon + 1e-9
        ]
        if bei01_tenors:
            available_groups.add("BEI01")
        if cs01_tenors:
            available_groups.add("CS01")
        group_availability[bucket.bucket_key] = available_groups

    best_tenors, _, _ = _calc_dv01_combination(bucket_keys, options)
    if not best_tenors:
        best_tenors = [choices[0][0] for choices in options]

    results: List[ResultRecord] = []
    for bucket, bucket_amount, dv01_tenor in zip(buckets, amounts, best_tenors):
        exposure = bucket_amount * dv01_tenor
        available_groups = group_availability.get(bucket.bucket_key, {"DV01"})
        risk_group_count = len(available_groups)
        if risk_group_count > 0:
            shared_tenor = dv01_tenor / risk_group_count
        else:
            shared_tenor = dv01_tenor
        bei01_tenor = shared_tenor if "BEI01" in available_groups else 0.0
        cs01_tenor = shared_tenor if "CS01" in available_groups else 0.0
        results.append(
            ResultRecord(
                bucket_key=bucket.bucket_key,
                amount=bucket_amount,
                dv01_tenor=dv01_tenor,
                bei01_tenor=bei01_tenor,
                cs01_tenor=cs01_tenor,
                dv01_exposure=exposure,
            )
        )

    return results


def results_to_positions(
    results: Sequence[ResultRecord],
    buckets: Mapping[str, BucketRecord],
) -> Dict[Tuple[str, str, float], float]:
    """Expand results into risk-group/currency/tenor positions."""

    positions: Dict[Tuple[str, str, float], float] = {}
    for result in results:
        bucket = buckets.get(result.bucket_key)
        if not bucket:
            continue
        currency = bucket.currency
        entries: List[Tuple[str, float]] = [("DV01", result.dv01_tenor)]
        if result.bei01_tenor > 0:
            entries.append(("BEI01", result.bei01_tenor))
        if result.cs01_tenor > 0:
            entries.append(("CS01", result.cs01_tenor))
        for risk_group, tenor in entries:
            key = (risk_group, currency, tenor)
            positions[key] = positions.get(key, 0.0) + result.amount
    return positions


def build_recommendations(
    baseline: Mapping[Tuple[str, str, float], float],
    current: Mapping[Tuple[str, str, float], float],
    margin: float,
) -> List[Recommendation]:
    """Compare two position sets and suggest trades beyond a margin."""

    keys = set(baseline) | set(current)
    recommendations: List[Recommendation] = []
    for key in keys:
        baseline_amount = baseline.get(key, 0.0)
        current_amount = current.get(key, 0.0)
        difference = current_amount - baseline_amount
        if abs(difference) <= max(margin, 0.0):
            continue
        action = "Buy" if difference > 0 else "Sell"
        recommendations.append(
            Recommendation(
                action=action,
                risk_group=key[0],
                currency=key[1],
                tenor=key[2],
                amount=abs(difference),
            )
        )

    recommendations.sort(key=lambda rec: (rec.risk_group, rec.currency, rec.tenor))
    return recommendations

