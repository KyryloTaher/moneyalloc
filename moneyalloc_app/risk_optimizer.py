"""Risk-equal portfolio optimiser for distribution planning.

The solver takes a set of *initial distributions*—the target weights for each
bucket/currency-tenor combination—and translates them into *risk-adjusted final
allocations*.  The process unfolds in the following steps:

1. **Variable discovery** – For every bucket/sleeve pair that has both a
   supplied yield and duration we create a decision variable.  Buckets without a
   usable instrument for a sleeve never receive a variable, so they simply drop
   out of the optimisation while the other sleeves still participate.
2. **Objective construction** – We maximise total portfolio yield by asking the
   linear programme to minimise the negative yields of the discovered decision
   variables.
3. **Constraint assembly** – Two families of linear constraints are built:
   * *Bucket totals*: the variables that belong to the same bucket must sum to
     that bucket's target weight (normalised to 1.0).  This preserves the user's
     initial distribution across currencies/tenors.
   * *Equal risk across sleeves*: for every pair of sleeves that are present in
     the data we enforce equality of risk contributions by equating their
     duration-weighted exposures.
4. **Solve and collate** – The linear programme is solved with SciPy's HiGHS
   backend.  The decision vector is then aggregated by bucket and sleeve to
   yield the final risk-balanced allocations.

The public :func:`run_risk_equal_optimization` function encapsulates this flow
and returns the allocations together with the achieved risk statistics.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported only for typing
    import numpy as _np


Bucket = str
Sleeve = str  # "rates", "tips" or "credit"


@dataclass(slots=True)
class ProblemSpec:
    """Input specification for the risk optimisation routine.

    The :class:`ProblemSpec` mirrors the spreadsheet-style inputs the finance
    team provides:

    ``bucket_weights``
        Target percentage weights for each bucket.  The solver normalises them
        by 100 so the resulting allocations are expressed as fractions of the
        total portfolio.

    ``*_yields``
        Expected yields (in percent) for each sleeve.  A ``None`` entry means no
        investable instrument exists for that bucket/sleeve pair, so it is
        omitted from the optimisation entirely.

    ``durations``
        Mapping from ``(bucket, sleeve)`` to the duration used when computing
        risk contributions.
    """

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


@dataclass(slots=True)
class _Workspace:
    """Internal representation of the linear programme variables and data."""

    keys: List[Tuple[Bucket, Sleeve]]
    yields: "_np.ndarray"
    durations_by_sleeve: Dict[Sleeve, "_np.ndarray"]


def _build_workspace(spec: ProblemSpec, np) -> _Workspace:
    """Collect optimisation variables and per-sleeve duration arrays."""

    keys: List[Tuple[Bucket, Sleeve]] = []
    yield_list: List[float] = []
    duration_lists: Dict[Sleeve, List[float]] = {"rates": [], "tips": [], "credit": []}

    def maybe_add(bucket: Bucket, sleeve: Sleeve, yield_value: Optional[float]) -> None:
        if yield_value is None:
            return
        duration_key = (bucket, sleeve)
        if duration_key not in spec.durations:
            return

        keys.append((bucket, sleeve))
        yield_list.append(float(yield_value))

        for target_sleeve in ("rates", "tips", "credit"):
            if target_sleeve == sleeve:
                duration_lists[target_sleeve].append(float(spec.durations[duration_key]))
            else:
                duration_lists[target_sleeve].append(0.0)

    buckets = set(spec.bucket_weights.keys())
    for bucket in buckets:
        maybe_add(bucket, "rates", spec.rates_yields.get(bucket))
        maybe_add(bucket, "tips", spec.tips_yields.get(bucket))
        maybe_add(bucket, "credit", spec.credit_yields.get(bucket))

    if not keys:
        raise ValueError("No decision variables defined. Provide yields and durations.")

    yields_array = np.array(yield_list) / 100.0
    durations_arrays = {sleeve: np.array(values) for sleeve, values in duration_lists.items()}

    return _Workspace(keys=keys, yields=yields_array, durations_by_sleeve=durations_arrays)


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

    workspace = _build_workspace(spec, np)
    keys = workspace.keys
    buckets = set(spec.bucket_weights.keys())
    variable_count = len(keys)

    y_arr = workspace.yields
    d_rates_arr = workspace.durations_by_sleeve["rates"]
    d_tips_arr = workspace.durations_by_sleeve["tips"]
    d_credit_arr = workspace.durations_by_sleeve["credit"]

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
    sleeves_present = {
        sleeve: any(existing_sleeve == sleeve for _bucket, existing_sleeve in keys)
        for sleeve in ("rates", "tips", "credit")
    }

    def add_equal_risk_constraint(left: Sleeve, right: Sleeve) -> None:
        if not (sleeves_present[left] and sleeves_present[right]):
            return
        left_arr = {
            "rates": d_rates_arr,
            "tips": d_tips_arr,
            "credit": d_credit_arr,
        }[left]
        right_arr = {
            "rates": d_rates_arr,
            "tips": d_tips_arr,
            "credit": d_credit_arr,
        }[right]
        a_eq.append(left_arr.copy() - right_arr.copy())
        b_eq.append(0.0)

    add_equal_risk_constraint("rates", "tips")
    add_equal_risk_constraint("rates", "credit")
    add_equal_risk_constraint("tips", "credit")

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

