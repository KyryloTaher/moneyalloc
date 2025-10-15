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
    bucket_currencies: Dict[Bucket, str]


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
    available: Dict[Sleeve, float] = dict(previous)

    for (source_bucket, sleeve), tenor in tenors.items():
        if source_bucket != bucket:
            continue
        if tenor is None:
            continue
        tenor_value = float(tenor)
        if tenor_value <= 0.0:
            continue
        if tenor_value - bucket_horizon > _FLOAT_TOLERANCE:
            raise ValueError(
                f"Tenor {tenor_value} exceeds horizon {bucket_horizon} for bucket {bucket}."
            )
        previous_tenor = available.get(sleeve)
        if previous_tenor is None:
            available[sleeve] = tenor_value
        else:
            available[sleeve] = min(previous_tenor, tenor_value)

    if not available:
        raise ValueError(f"No sleeves with tenor <= horizon found for bucket {bucket}.")

    return available


def run_risk_equal_optimization(spec: ProblemSpec) -> RiskOptimizationResult:
    """Optimise allocations subject to risk and currency balancing constraints."""

    import math

    normalised = _normalise_weights(spec.bucket_weights)
    ordered_buckets = tuple(_sorted_buckets(normalised, spec.bucket_horizons))
    if not ordered_buckets:
        raise ValueError("No buckets supplied for optimisation.")

    previous_sleeves: Dict[Sleeve, float] = {}
    bucket_sleeve_tenors: Dict[Bucket, Dict[Sleeve, float]] = {}

    for bucket in ordered_buckets:
        sleeves = _tenors_for_bucket(
            bucket,
            horizons=spec.bucket_horizons,
            tenors=spec.tenors,
            previous=previous_sleeves,
        )
        if not sleeves:
            raise ValueError(f"No sleeves available for bucket {bucket}.")
        bucket_sleeve_tenors[bucket] = sleeves
        previous_sleeves = dict(sleeves)

    variables: list[tuple[Bucket, Sleeve, float]] = []
    index_map: Dict[tuple[Bucket, Sleeve], int] = {}

    for bucket in ordered_buckets:
        sleeves = bucket_sleeve_tenors[bucket]
        for sleeve, tenor in sorted(sleeves.items()):
            if tenor <= 0.0:
                raise ValueError(f"Invalid tenor {tenor!r} for bucket {bucket} and sleeve {sleeve}.")
            index = len(variables)
            variables.append((bucket, sleeve, float(tenor)))
            index_map[(bucket, sleeve)] = index

    if not variables:
        raise ValueError("No investable sleeves supplied for optimisation.")

    num_vars = len(variables)
    rows: list[list[float]] = []
    rhs: list[float] = []

    # Bucket share constraints: the shares assigned within each bucket must sum
    # to the bucket weight.
    for bucket in ordered_buckets:
        indices = [index_map[(bucket, sleeve)] for sleeve in bucket_sleeve_tenors[bucket]]
        row = [0.0] * num_vars
        for index in indices:
            row[index] = 1.0
        rows.append(row)
        rhs.append(normalised[bucket])

    # Risk equalisation: aggregate DV01/BEI01/CS01 exposure (share * tenor)
    # must match across sleeves that are present.
    sleeves_present = sorted({sleeve for _bucket, sleeve, _tenor in variables})
    if len(sleeves_present) > 1:
        base = sleeves_present[0]
        for sleeve in sleeves_present[1:]:
            row = [0.0] * num_vars
            for index, (_bucket, current_sleeve, tenor) in enumerate(variables):
                if current_sleeve == sleeve:
                    row[index] += tenor
                elif current_sleeve == base:
                    row[index] -= tenor
            if any(value != 0.0 for value in row):
                rows.append(row)
                rhs.append(0.0)

    # Currency balancing: for a given risk sleeve and tenor, currencies should
    # carry equal weight.
    def _tenor_group_key(tenor_value: float) -> float:
        return round(tenor_value, 9)

    grouped: Dict[tuple[Sleeve, float], Dict[str, list[int]]] = {}
    for index, (bucket, sleeve, tenor) in enumerate(variables):
        currency = spec.bucket_currencies.get(bucket, "")
        key = (sleeve, _tenor_group_key(tenor))
        currency_map = grouped.setdefault(key, {})
        currency_map.setdefault(currency, []).append(index)

    for currency_map in grouped.values():
        if len(currency_map) <= 1:
            continue
        currencies = sorted(currency_map)
        reference = currencies[0]
        ref_indices = currency_map[reference]
        if not ref_indices:
            continue
        for currency in currencies[1:]:
            indices = currency_map[currency]
            if not indices:
                continue
            row = [0.0] * num_vars
            for idx in indices:
                row[idx] += 1.0
            for idx in ref_indices:
                row[idx] -= 1.0
            if any(value != 0.0 for value in row):
                rows.append(row)
                rhs.append(0.0)

    num_equations = len(rows)
    if num_equations == 0:
        raise ValueError("No constraints supplied for optimisation.")

    def _solve_normal_equations(matrix: list[list[float]], vector: list[float]) -> list[float]:
        size = len(matrix)
        augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]

        for col in range(size):
            pivot_row = max(range(col, size), key=lambda r: abs(augmented[r][col]))
            pivot_value = augmented[pivot_row][col]
            if abs(pivot_value) <= 1e-12:
                raise ValueError("Unable to solve optimisation system.")
            if pivot_row != col:
                augmented[col], augmented[pivot_row] = augmented[pivot_row], augmented[col]

            pivot_value = augmented[col][col]
            for idx in range(col, size + 1):
                augmented[col][idx] /= pivot_value

            for row_index in range(size):
                if row_index == col:
                    continue
                factor = augmented[row_index][col]
                if abs(factor) <= 1e-12:
                    continue
                for idx in range(col, size + 1):
                    augmented[row_index][idx] -= factor * augmented[col][idx]

        return [augmented[i][size] for i in range(size)]

    num_vars = len(variables)

    def _solve_with_multipliers() -> list[float]:
        """Solve the equality constrained system using Lagrange multipliers."""

        num_equations = len(rows)
        gram: list[list[float]] = [[0.0 for _ in range(num_equations)] for _ in range(num_equations)]

        for i, row_i in enumerate(rows):
            for j, row_j in enumerate(rows):
                gram[i][j] = sum(value_i * value_j for value_i, value_j in zip(row_i, row_j))
            gram[i][i] += 1e-12

        try:
            multipliers = _solve_normal_equations(gram, rhs)
        except ValueError as exc:
            raise ValueError("Unable to equalise risk under the supplied constraints.") from exc

        solution = [0.0 for _ in range(num_vars)]
        for column in range(num_vars):
            solution[column] = sum(rows[row_index][column] * multipliers[row_index] for row_index in range(num_equations))
        return solution

    solution = _solve_with_multipliers()

    residual_sum = 0.0
    for row, target in zip(rows, rhs):
        predicted = sum(value * row[index] for index, value in enumerate(solution))
        residual = predicted - target
        residual_sum += residual * residual

    residual_norm = math.sqrt(residual_sum)
    if residual_norm > 1e-8:
        raise ValueError("Unable to equalise risk under the supplied constraints.")

    min_value = min(solution)
    if min_value < -1e-9:
        raise ValueError("Optimisation produced negative allocations under the constraints supplied.")

    solution = [value if value > 0.0 else 0.0 for value in solution]

    # Verify that the bucket totals still match the targets after clamping.
    for bucket in ordered_buckets:
        indices = [index_map[(bucket, sleeve)] for sleeve in bucket_sleeve_tenors[bucket]]
        bucket_total = sum(solution[index] for index in indices)
        if not math.isclose(bucket_total, normalised[bucket], rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("Unable to satisfy bucket allocation targets while balancing risk.")

    # Confirm risk balancing across sleeves.
    if len(sleeves_present) > 1:
        exposure_by_sleeve: Dict[Sleeve, float] = {}
        for (bucket, sleeve, tenor), value in zip(variables, solution):
            exposure_by_sleeve[sleeve] = exposure_by_sleeve.get(sleeve, 0.0) + tenor * value
        exposures = list(exposure_by_sleeve.values())
        target_exposure = exposures[0]
        for exposure in exposures[1:]:
            if not math.isclose(exposure, target_exposure, rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError("Risk exposures could not be equalised across sleeves.")

    allocations: Dict[Tuple[Bucket, Sleeve], float] = {}
    by_bucket: Dict[Bucket, float] = {}
    by_sleeve: Dict[Sleeve, float] = {}

    for (bucket, sleeve, _tenor), value in zip(variables, solution):
        if value <= _FLOAT_TOLERANCE:
            continue
        allocations[(bucket, sleeve)] = value
        by_bucket[bucket] = by_bucket.get(bucket, 0.0) + value
        by_sleeve[sleeve] = by_sleeve.get(sleeve, 0.0) + value

    total_allocated = sum(by_bucket.values())
    if total_allocated <= _FLOAT_TOLERANCE:
        raise ValueError("Optimisation produced zero allocation. Check bucket weights and tenors.")

    allocations = {key: value for key, value in allocations.items()}
    by_bucket = {bucket: value for bucket, value in by_bucket.items()}
    by_sleeve = {sleeve: value for sleeve, value in by_sleeve.items()}

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

