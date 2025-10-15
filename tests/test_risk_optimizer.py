import math

import pytest

from moneyalloc_app.risk_optimizer import (
    ProblemSpec,
    _sorted_buckets,
    _tenors_for_bucket,
    run_risk_equal_optimization,
)


def _build_spec(bucket_weights, horizons, tenors, currencies=None):
    if currencies is None:
        currencies = {bucket: "USD" for bucket in bucket_weights}
    return ProblemSpec(
        bucket_weights=bucket_weights,
        bucket_horizons=horizons,
        tenors=tenors,
        bucket_currencies=currencies,
    )


def _effective_tenors(spec: ProblemSpec):
    horizons = spec.bucket_horizons
    ordered = tuple(_sorted_buckets(spec.bucket_weights, horizons))
    effective = {}
    previous = {}
    for bucket in ordered:
        sleeves = _tenors_for_bucket(
            bucket,
            horizons=horizons,
            tenors=spec.tenors,
            previous=previous,
        )
        effective[bucket] = sleeves
        previous = sleeves
    return effective


def test_bucket_allocations_follow_weights():
    spec = _build_spec(
        bucket_weights={"1Y": 60.0, "3Y": 40.0},
        horizons={"1Y": 1.0, "3Y": 3.0},
        tenors={("1Y", "rates"): 0.5, ("3Y", "rates"): 1.5, ("3Y", "credit"): 2.5},
    )

    result = run_risk_equal_optimization(spec)

    assert math.isclose(sum(result.by_bucket.values()), 1.0, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["1Y"], 0.6, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["3Y"], 0.4, rel_tol=1e-9)

    bucket_one_total = sum(
        value for (bucket, _), value in result.allocations.items() if bucket == "1Y"
    )
    bucket_three_total = sum(
        value for (bucket, _), value in result.allocations.items() if bucket == "3Y"
    )
    assert math.isclose(bucket_one_total, 0.6, rel_tol=1e-9)
    assert math.isclose(bucket_three_total, 0.4, rel_tol=1e-9)

    # Exposure should be equal across the active sleeves.
    effective_tenors = _effective_tenors(spec)
    exposure_rates = sum(
        value * effective_tenors[bucket][sleeve]
        for (bucket, sleeve), value in result.allocations.items()
        if sleeve == "rates"
    )
    exposure_credit = sum(
        value * effective_tenors[bucket][sleeve]
        for (bucket, sleeve), value in result.allocations.items()
        if sleeve == "credit"
    )
    assert math.isclose(exposure_rates, exposure_credit, rel_tol=1e-9)


def test_global_exposure_balancing_across_buckets():
    spec = _build_spec(
        bucket_weights={"6M": 30.0, "1Y": 30.0, "2Y": 40.0},
        horizons={"6M": 0.5, "1Y": 1.0, "2Y": 2.0},
        tenors={
            ("6M", "rates"): 0.05,
            ("1Y", "rates"): 0.1,
            ("2Y", "rates"): 1.5,
            ("2Y", "credit"): 1.8,
            ("2Y", "tips"): 1.0,
        },
    )

    result = run_risk_equal_optimization(spec)

    effective_tenors = _effective_tenors(spec)
    exposures = {}
    for (bucket, sleeve), value in result.allocations.items():
        tenor = effective_tenors[bucket][sleeve]
        exposures[sleeve] = exposures.get(sleeve, 0.0) + tenor * value

    exposure_values = list(exposures.values())
    assert len(exposure_values) == 3
    first = exposure_values[0]
    for value in exposure_values[1:]:
        assert math.isclose(first, value, rel_tol=1e-9)


def test_currency_balancing_within_equal_tenors():
    spec = _build_spec(
        bucket_weights={"USD::1Y": 50.0, "EUR::1Y": 50.0},
        horizons={"USD::1Y": 1.0, "EUR::1Y": 1.0},
        tenors={("USD::1Y", "rates"): 0.5, ("EUR::1Y", "rates"): 0.5},
        currencies={"USD::1Y": "USD", "EUR::1Y": "EUR"},
    )

    result = run_risk_equal_optimization(spec)

    usd_share = result.allocations[("USD::1Y", "rates")]
    eur_share = result.allocations[("EUR::1Y", "rates")]

    assert math.isclose(usd_share, 0.5, rel_tol=1e-9)
    assert math.isclose(eur_share, 0.5, rel_tol=1e-9)
    assert math.isclose(usd_share, eur_share, rel_tol=1e-9)

def test_currency_balancing_within_equal_tenors():
    spec = _build_spec(
        bucket_weights={"USD::1Y": 50.0, "EUR::1Y": 50.0},
        horizons={"USD::1Y": 1.0, "EUR::1Y": 1.0},
        tenors={("USD::1Y", "rates"): 0.5, ("EUR::1Y", "rates"): 0.5},
        currencies={"USD::1Y": "USD", "EUR::1Y": "EUR"},
    )

def test_equalises_risk_with_currency_balancing():
    spec = _build_spec(
        bucket_weights={
            "USD::6M": 25.0,
            "USD::2Y": 25.0,
            "EUR::6M": 25.0,
            "EUR::2Y": 25.0,
        },
        horizons={
            "USD::6M": 0.5,
            "USD::2Y": 2.0,
            "EUR::6M": 0.5,
            "EUR::2Y": 2.0,
        },
        tenors={
            ("USD::6M", "rates"): 0.5,
            ("USD::2Y", "rates"): 1.5,
            ("USD::2Y", "credit"): 1.8,
            ("EUR::6M", "rates"): 0.5,
            ("EUR::2Y", "rates"): 1.5,
            ("EUR::2Y", "credit"): 1.8,
        },
        currencies={
            "USD::6M": "USD",
            "USD::2Y": "USD",
            "EUR::6M": "EUR",
            "EUR::2Y": "EUR",
        },
    )

    result = run_risk_equal_optimization(spec)

    usd_rates = result.allocations[("USD::6M", "rates")]
    eur_rates = result.allocations[("EUR::6M", "rates")]
    assert math.isclose(usd_rates, eur_rates, rel_tol=1e-9)

    effective_tenors = _effective_tenors(spec)
    exposures = {}
    for (bucket, sleeve), value in result.allocations.items():
        tenor = effective_tenors[bucket][sleeve]
        exposures[sleeve] = exposures.get(sleeve, 0.0) + tenor * value

    values = list(exposures.values())
    first = values[0]
    for value in values[1:]:
        assert math.isclose(first, value, rel_tol=1e-9)


def test_handles_under_determined_balancing_system():
    spec = _build_spec(
        bucket_weights={"6M": 60.0, "2Y": 40.0},
        horizons={"6M": 0.5, "2Y": 2.0},
        tenors={
            ("6M", "rates"): 0.5,
            ("6M", "credit"): 0.5,
            ("2Y", "rates"): 1.5,
            ("2Y", "credit"): 1.8,
        },
    )

    result = run_risk_equal_optimization(spec)

    assert math.isclose(result.by_bucket["6M"], 0.6, rel_tol=1e-9)
    assert math.isclose(result.by_bucket["2Y"], 0.4, rel_tol=1e-9)

    effective_tenors = _effective_tenors(spec)
    exposure_rates = sum(
        value * effective_tenors[bucket][sleeve]
        for (bucket, sleeve), value in result.allocations.items()
        if sleeve == "rates"
    )
    exposure_credit = sum(
        value * effective_tenors[bucket][sleeve]
        for (bucket, sleeve), value in result.allocations.items()
        if sleeve == "credit"
    )

    assert math.isclose(exposure_rates, exposure_credit, rel_tol=1e-9)


def test_missing_horizon_information_is_rejected():
    spec = _build_spec(
        bucket_weights={"1Y": 100.0},
        horizons={},
        tenors={},
        currencies={"1Y": "USD"},
    )

    with pytest.raises(ValueError):
        run_risk_equal_optimization(spec)


def test_tenors_for_bucket_preserves_shorter_previous_tenor():
    horizons = {"1Y": 1.0, "3Y": 3.0}
    tenors = {("1Y", "rates"): 0.5, ("3Y", "rates"): 1.5}
    previous = {"rates": 0.5}

    sleeves = _tenors_for_bucket(
        "3Y", horizons=horizons, tenors=tenors, previous=previous
    )

    assert sleeves["rates"] == 0.5
