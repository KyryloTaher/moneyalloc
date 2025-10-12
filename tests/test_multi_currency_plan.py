import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from moneyalloc_app.app import DistributionDialog, PlanRow
from moneyalloc_app.models import Allocation, NONE_TIME_HORIZON_LABEL


class StubAllocationRepo:
    def __init__(self, allocations):
        self._allocations = allocations

    def get_all_allocations(self):
        return list(self._allocations)


class PlanBuilderHarness:
    _parse_currency_codes = staticmethod(DistributionDialog._parse_currency_codes)

    def __init__(self, allocations):
        self.repo = StubAllocationRepo(allocations)

    def build_plan(self, amount, tolerance, time_horizon, currency_filter):
        return DistributionDialog._build_plan(
            self,
            amount=amount,
            tolerance=tolerance,
            time_horizon=time_horizon,
            currency_filter=currency_filter,
        )


def test_multi_currency_allocation_filters_and_totals():
    allocation = Allocation(
        id=1,
        parent_id=None,
        name="Multi-currency",
        currency="EUR, USD",
        instrument=None,
        target_percent=100.0,
        include_in_rollup=True,
        notes="",
        sort_order=0,
        current_value=100.0,
        time_horizon=None,
    )

    harness = PlanBuilderHarness([allocation])

    plan_rows, _totals, currency_totals = harness.build_plan(
        amount=0.0, tolerance=0.0, time_horizon=None, currency_filter=None
    )

    assert len(plan_rows) == 1
    row = plan_rows[0]
    assert row.currencies == ("EUR", "USD")
    assert row.currency == "EUR, USD"
    assert set(currency_totals.keys()) == {"EUR", "USD"}
    assert currency_totals["EUR"]["current_total"] == pytest.approx(50.0)
    assert currency_totals["USD"]["current_total"] == pytest.approx(50.0)

    plan_rows_eur, _totals_eur, currency_totals_eur = harness.build_plan(
        amount=0.0, tolerance=0.0, time_horizon=None, currency_filter={"EUR"}
    )
    assert len(plan_rows_eur) == 1
    assert plan_rows_eur[0].currencies == ("EUR",)
    assert set(currency_totals_eur.keys()) == {"EUR"}

    plan_rows_usd, _totals_usd, currency_totals_usd = harness.build_plan(
        amount=0.0, tolerance=0.0, time_horizon=None, currency_filter={"USD"}
    )
    assert len(plan_rows_usd) == 1
    assert plan_rows_usd[0].currencies == ("USD",)
    assert set(currency_totals_usd.keys()) == {"USD"}


def test_non_risk_horizons_grouped_under_none_label():
    rows = [
        PlanRow(
            allocation_id=1,
            path="A",
            currencies=("USD",),
            time_horizon=None,
            target_share=10.0,
            current_value=0.0,
            current_share=0.0,
            target_value=0.0,
            recommended_change=0.0,
            share_diff=0.0,
            action="",
        ),
        PlanRow(
            allocation_id=2,
            path="B",
            currencies=("USD",),
            time_horizon=NONE_TIME_HORIZON_LABEL,
            target_share=15.0,
            current_value=0.0,
            current_share=0.0,
            target_value=0.0,
            recommended_change=0.0,
            share_diff=0.0,
            action="",
        ),
        PlanRow(
            allocation_id=3,
            path="C",
            currencies=("USD",),
            time_horizon="1Y",
            target_share=75.0,
            current_value=0.0,
            current_share=0.0,
            target_value=0.0,
            recommended_change=0.0,
            share_diff=0.0,
            action="",
        ),
    ]

    totals = DistributionDialog._summarize_non_risk_rows(rows)

    assert totals == {NONE_TIME_HORIZON_LABEL: 25.0}
