"""Core allocation and calculation utilities."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Dict, Iterable, List, Sequence, Tuple

from .database import AllocationRecord, BucketRecord, ResultRecord


@dataclass
class LeafAllocation:
    bucket_key: str
    time_horizon: float
    currency: str
    percentage: float


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
            for currency in currencies:
                bucket_key = f"{node.time_horizon}|{currency.upper()}"
                leaves.append(
                    LeafAllocation(
                        bucket_key=bucket_key,
                        time_horizon=node.time_horizon,
                        currency=currency.upper(),
                        percentage=current * 100.0,
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
    for bucket in buckets:
        bucket_amount = total_amount * (bucket.percentage / 100.0)
        amounts.append(bucket_amount)
        bucket_tenors = tenor_inputs.get(bucket.bucket_key, {})
        dv01_tenors = [t for t in bucket_tenors.get("DV01", []) if t <= bucket.time_horizon + 1e-9]
        if not dv01_tenors:
            # Default to min(time_horizon, 1) if no valid tenor provided
            fallback = min(bucket.time_horizon, 1.0)
            dv01_tenors = [fallback]
        options.append([(tenor, bucket_amount * tenor) for tenor in dv01_tenors])

    best_tenors, _, _ = _calc_dv01_combination(bucket_keys, options)
    if not best_tenors:
        best_tenors = [choices[0][0] for choices in options]

    risk_groups = ["DV01"]
    if any(tenor_inputs.get(key, {}).get("BEI01") for key in bucket_keys):
        risk_groups.append("BEI01")
    if any(tenor_inputs.get(key, {}).get("CS01") for key in bucket_keys):
        risk_groups.append("CS01")

    risk_group_count = len(risk_groups)

    results: List[ResultRecord] = []
    for bucket, bucket_amount, dv01_tenor in zip(buckets, amounts, best_tenors):
        exposure = bucket_amount * dv01_tenor
        if risk_group_count > 0:
            shared_tenor = dv01_tenor / risk_group_count
        else:
            shared_tenor = dv01_tenor
        bei01_tenor = shared_tenor if "BEI01" in risk_groups else 0.0
        cs01_tenor = shared_tenor if "CS01" in risk_groups else 0.0
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

