import math

import pytest

from moneyalloc_app.risk_optimizer import ProblemSpec, run_risk_equal_optimization


def _build_spec(bucket_weights, horizons, tenors):
    return ProblemSpec(
        bucket_weights=bucket_weights,
        bucket_horizons=horizons,
        tenors=tenors,
    )


def test_cascading_allocation_respects_bucket_weights():
    spec = _build_spec(
        bucket_weights={"1Y": 60.0, "3Y": 40.0},
        horizons={"1Y": 1.0, "3Y": 3.0},
        tenors={("1Y", "rates"): 0.5, ("3Y", "rates"): 1.5, ("3Y", "credit"): 2.5},
    )

    result = run_risk_equal_optimization(spec)

    assert math.isclose(sum(result.by_bucket.values()), 1.0, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["1Y"], 0.6, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["3Y"], 0.4, rel_tol=1e-9)


def test_cascading_allocation_is_monotonic():
    spec = _build_spec(
        bucket_weights={"6M": 30.0, "1Y": 30.0, "2Y": 40.0},
        horizons={"6M": 0.5, "1Y": 1.0, "2Y": 2.0},
        tenors={
            ("6M", "rates"): 0.25,
            ("1Y", "rates"): 0.75,
            ("2Y", "rates"): 1.5,
            ("2Y", "credit"): 1.8,
        },
    )

    result = run_risk_equal_optimization(spec)

    # Later buckets should never reduce the cumulative share allocated to an existing sleeve.
    six_month_share = result.allocations.get(("6M", "rates"), 0.0)
    one_year_increment = result.allocations.get(("1Y", "rates"), 0.0)
    two_year_increment = result.allocations.get(("2Y", "rates"), 0.0)

    one_year_cumulative = six_month_share + one_year_increment
    two_year_cumulative = one_year_cumulative + two_year_increment

    assert one_year_cumulative >= six_month_share
    assert two_year_cumulative >= one_year_cumulative


def test_shorter_tenors_receive_higher_priority():
    spec = _build_spec(
        bucket_weights={"1Y": 40.0, "3Y": 60.0},
        horizons={"1Y": 1.0, "3Y": 3.0},
        tenors={
            ("1Y", "rates"): 0.5,
            ("3Y", "rates"): 1.0,
            ("3Y", "tips"): 2.0,
        },
    )

    result = run_risk_equal_optimization(spec)

    # Remaining allocation in the longer bucket should favour the shorter tenor sleeve.
    long_bucket_rates = result.allocations[("3Y", "rates")]
    long_bucket_tips = result.allocations.get(("3Y", "tips"), 0.0)
    assert long_bucket_rates >= long_bucket_tips


def test_missing_horizon_information_is_rejected():
    spec = _build_spec(
        bucket_weights={"1Y": 100.0},
        horizons={},
        tenors={},
    )

    with pytest.raises(ValueError):
        run_risk_equal_optimization(spec)
