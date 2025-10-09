import math

import pytest

pytest.importorskip("numpy")
pytest.importorskip("scipy.optimize")

from moneyalloc_app.risk_optimizer import ProblemSpec, run_risk_equal_optimization


def _build_spec(
    *,
    bucket_weights,
    rates=None,
    tips=None,
    credit=None,
    durations=None,
):
    return ProblemSpec(
        bucket_weights=bucket_weights,
        rates_yields=rates or {},
        tips_yields=tips or {},
        credit_yields=credit or {},
        durations=durations or {},
    )


def test_solver_handles_missing_sleeves():
    spec = _build_spec(
        bucket_weights={"USD": 100.0},
        rates={"USD": 4.0},
        durations={("USD", "rates"): 5.0},
    )

    result = run_risk_equal_optimization(spec)

    assert math.isclose(result.by_bucket["USD"], 1.0, rel_tol=1e-9)
    assert result.by_sleeve["rates"] == pytest.approx(1.0)
    assert result.by_sleeve["tips"] == pytest.approx(0.0)
    assert result.by_sleeve["credit"] == pytest.approx(0.0)


def test_solver_enforces_equal_risk_for_available_sleeves():
    spec = _build_spec(
        bucket_weights={"USD": 100.0},
        tips={"USD": 3.0},
        credit={"USD": 6.0},
        durations={("USD", "tips"): 4.0, ("USD", "credit"): 8.0},
    )

    result = run_risk_equal_optimization(spec)

    assert math.isclose(result.by_bucket["USD"], 1.0, rel_tol=1e-9)
    assert math.isclose(result.K_tips, result.K_credit, rel_tol=1e-9)


def test_equal_risk_still_considers_all_present_sleeves():
    spec = _build_spec(
        bucket_weights={"USD": 60.0, "EUR": 40.0},
        rates={"USD": 5.0},
        tips={"USD": 4.0},
        credit={"EUR": 6.0},
        durations={
            ("USD", "rates"): 4.0,
            ("USD", "tips"): 2.0,
            ("EUR", "credit"): 2.0,
        },
    )

    result = run_risk_equal_optimization(spec)

    assert math.isclose(result.by_bucket["USD"], 0.6, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["EUR"], 0.4, rel_tol=1e-9)
    assert math.isclose(result.K_rates, result.K_tips, rel_tol=1e-9)
    assert math.isclose(result.K_rates, result.K_credit, rel_tol=1e-9)


def test_full_flow_preserves_targets_and_balances_risk():
    spec = _build_spec(
        bucket_weights={"USD 5Y": 40.0, "USD 10Y": 30.0, "EUR 10Y": 30.0},
        rates={"USD 5Y": 4.2, "USD 10Y": 4.6, "EUR 10Y": 3.1},
        tips={"USD 5Y": 3.8},
        credit={"USD 10Y": 5.4, "EUR 10Y": 5.9},
        durations={
            ("USD 5Y", "rates"): 4.0,
            ("USD 10Y", "rates"): 8.0,
            ("EUR 10Y", "rates"): 7.5,
            ("USD 5Y", "tips"): 5.0,
            ("USD 10Y", "credit"): 6.0,
            ("EUR 10Y", "credit"): 5.5,
        },
    )

    result = run_risk_equal_optimization(spec)

    # Bucket targets are respected after normalisation to 1.0
    assert math.isclose(result.by_bucket["USD 5Y"], 0.4, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["USD 10Y"], 0.3, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["EUR 10Y"], 0.3, rel_tol=1e-9)

    # Equal risk holds for every sleeve that exists in the input data
    assert math.isclose(result.K_rates, result.K_tips, rel_tol=1e-9)
    assert math.isclose(result.K_rates, result.K_credit, rel_tol=1e-9)

    # Allocations sum to the full portfolio
    total_allocated = sum(result.allocations.values())
    assert math.isclose(total_allocated, 1.0, rel_tol=1e-9)
