"""Risk-equal portfolio optimiser for distribution planning."""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


Bucket = str
Sleeve = str  # "rates", "tips" or "credit"


@dataclass(slots=True)
class ProblemSpec:
    """Input specification for the risk optimisation routine."""

    bucket_weights: Dict[Bucket, float]
    rates_yields: Dict[Bucket, Optional[float]]
    tips_yields: Dict[Bucket, Optional[float]]
    credit_yields: Dict[Bucket, Optional[float]]
    durations: Dict[Tuple[Bucket, Sleeve], float]


@dataclass(slots=True)
class RiskOptimizationResult:
    """Container for the outcome of the optimisation."""

    allocations: Dict[Tuple[Bucket, Sleeve], float]
    by_bucket: Dict[Bucket, float]
    by_sleeve: Dict[Sleeve, float]
    K_rates: float
    K_tips: float
    K_credit: float
    portfolio_yield: float


_NUMPY = None
_LINPROG = None


def _load_dependencies():
    global _NUMPY, _LINPROG
    if _NUMPY is not None and _LINPROG is not None:
        return _NUMPY, _LINPROG

    numpy_spec = importlib.util.find_spec("numpy")
    if numpy_spec is None:
        raise RuntimeError(
            "numpy is required for risk calculations. Install numpy to enable this feature."
        )
    scipy_spec = importlib.util.find_spec("scipy.optimize")
    if scipy_spec is None:
        raise RuntimeError(
            "scipy is required for risk calculations. Install scipy to enable this feature."
        )

    numpy_module = importlib.import_module("numpy")
    scipy_optimize = importlib.import_module("scipy.optimize")
    _NUMPY = numpy_module
    _LINPROG = scipy_optimize.linprog
    return _NUMPY, _LINPROG


def run_risk_equal_optimization(spec: ProblemSpec) -> RiskOptimizationResult:
    """Solve the risk-equal linear programme for the provided specification."""

    np, linprog = _load_dependencies()

    keys: List[Tuple[Bucket, Sleeve]] = []
    yields: List[float] = []
    d_rates: List[float] = []
    d_tips: List[float] = []
    d_credit: List[float] = []

    def maybe_add(bucket: Bucket, sleeve: Sleeve, yield_value: Optional[float]) -> None:
        if yield_value is None:
            return
        if (bucket, sleeve) not in spec.durations:
            return
        keys.append((bucket, sleeve))
        yields.append(float(yield_value))
        d_rates.append(spec.durations.get((bucket, "rates"), 0.0) if sleeve == "rates" else 0.0)
        d_tips.append(spec.durations.get((bucket, "tips"), 0.0) if sleeve == "tips" else 0.0)
        d_credit.append(spec.durations.get((bucket, "credit"), 0.0) if sleeve == "credit" else 0.0)

    buckets = set(spec.bucket_weights.keys())
    for bucket in buckets:
        maybe_add(bucket, "rates", spec.rates_yields.get(bucket))
        maybe_add(bucket, "tips", spec.tips_yields.get(bucket))
        maybe_add(bucket, "credit", spec.credit_yields.get(bucket))

    variable_count = len(keys)
    if variable_count == 0:
        raise ValueError("No decision variables defined. Provide yields and durations.")

    y_arr = np.array(yields) / 100.0
    d_rates_arr = np.array(d_rates)
    d_tips_arr = np.array(d_tips)
    d_credit_arr = np.array(d_credit)

    # Objective: maximise sum(x_i * y_i) -> minimise -sum(...)
    objective = -y_arr

    a_eq: List[Iterable[float]] = []
    b_eq: List[float] = []

    # Bucket-sum constraints: each bucket must match its target weight
    for bucket in buckets:
        row = np.zeros(variable_count)
        for index, (bucket_name, _sleeve) in enumerate(keys):
            if bucket_name == bucket:
                row[index] = 1.0
        a_eq.append(row)
        b_eq.append(spec.bucket_weights[bucket] / 100.0)

    # Equal-risk constraints
    a_eq.append(d_rates_arr.copy() - d_tips_arr.copy())
    b_eq.append(0.0)
    a_eq.append(d_rates_arr.copy() - d_credit_arr.copy())
    b_eq.append(0.0)

    a_eq_matrix = np.vstack(a_eq)
    b_eq_vector = np.array(b_eq)

    bounds = [(0.0, None) for _ in range(variable_count)]

    result = linprog(objective, A_eq=a_eq_matrix, b_eq=b_eq_vector, bounds=bounds, method="highs")

    if not result.success:
        raise RuntimeError(f"Optimization failed: {result.message}")

    solution = result.x

    k_rates = float(np.dot(d_rates_arr, solution))
    k_tips = float(np.dot(d_tips_arr, solution))
    k_credit = float(np.dot(d_credit_arr, solution))
    portfolio_yield = float(np.dot(y_arr, solution))

    allocations: Dict[Tuple[Bucket, Sleeve], float] = {}
    for index, key in enumerate(keys):
        allocations[key] = float(solution[index])

    by_bucket: Dict[Bucket, float] = {bucket: 0.0 for bucket in buckets}
    for (bucket, _sleeve), value in allocations.items():
        by_bucket[bucket] += value

    by_sleeve: Dict[Sleeve, float] = {"rates": 0.0, "tips": 0.0, "credit": 0.0}
    for (_bucket, sleeve), value in allocations.items():
        by_sleeve[sleeve] += value

    return RiskOptimizationResult(
        allocations=allocations,
        by_bucket=by_bucket,
        by_sleeve=by_sleeve,
        K_rates=k_rates,
        K_tips=k_tips,
        K_credit=k_credit,
        portfolio_yield=portfolio_yield,
    )


__all__ = [
    "ProblemSpec",
    "RiskOptimizationResult",
    "run_risk_equal_optimization",
]

