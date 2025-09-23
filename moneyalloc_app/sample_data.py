"""Sample dataset used to populate the application for the first time."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .db import AllocationRepository
from .models import Allocation


@dataclass
class AllocationSeed:
    name: str
    target_percent: float
    currency: Optional[str] = None
    instrument: Optional[str] = None
    time_horizon: Optional[str] = None
    include: bool = True
    notes: str = ""
    children: Iterable["AllocationSeed"] | None = None

    def as_allocation(self, repo: AllocationRepository, parent_id: Optional[int]) -> Allocation:
        return Allocation(
            id=None,
            parent_id=parent_id,
            name=self.name,
            currency=self.currency,
            instrument=self.instrument,
            target_percent=self.target_percent,
            include_in_rollup=self.include,
            notes=self.notes,
            sort_order=repo.get_next_sort_order(parent_id),
            time_horizon=self.time_horizon,
        )


SAMPLE_ALLOCATIONS: list[AllocationSeed] = [
    AllocationSeed(
        name="Buffer (1 month income)",
        target_percent=16.67,
        include=False,
        notes="High level bucket that keeps one month worth of income accessible.",
        children=[
            AllocationSeed(
                name="UAH",
                target_percent=33.33,
                currency="UAH",
                notes="Local currency reserves split equally between cash and card balance.",
                children=[
                    AllocationSeed(
                        name="Cash",
                        target_percent=50.0,
                        currency="UAH",
                        include=True,
                        notes="Emergency banknotes stored at home.",
                        children=[
                            AllocationSeed(
                                name="Cash home",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                                notes="Daily emergency stash kept at home.",
                            ),
                            AllocationSeed(
                                name="Cash pocket",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                                notes="Cash kept on hand for quick access.",
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="Card",
                        target_percent=50.0,
                        currency="UAH",
                        include=True,
                        notes="Balances on debit cards dedicated to the buffer.",
                        children=[
                            AllocationSeed(
                                name="Card balance",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                                notes="Primary card used for unexpected expenses.",
                            ),
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                                notes="Interest-bearing card balance reserved for the buffer.",
                            ),
                        ],
                    ),
                ],
            ),
            AllocationSeed(
                name="Card balance, %",
                target_percent=33.33,
                currency="EUR",
                include=True,
                notes="Euro-denominated buffer earning interest.",
            ),
            AllocationSeed(
                name="Card balance, % (USD)",
                target_percent=33.33,
                currency="USD",
                include=True,
                notes="USD buffer held on an interest bearing account.",
            ),
        ],
    ),
    AllocationSeed(
        name="Insurance",
        target_percent=16.67,
        include=False,
        notes="Insurance buckets cover job loss, medical expenses and auto repairs.",
        children=[
            AllocationSeed(
                name="Job (3 month income)",
                target_percent=16.67,
                include=False,
                notes="Savings that secure income in case of job loss.",
                children=[
                    AllocationSeed(
                        name="UAH card balance, %",
                        target_percent=33.33,
                        currency="UAH",
                        include=True,
                    ),
                    AllocationSeed(
                        name="EUR",
                        target_percent=33.33,
                        currency="EUR",
                        include=False,
                        notes="Euro denominated safe instruments.",
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                            AllocationSeed(
                                name="Gov",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                notes="Government bonds and ETFs.",
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds Gov 3-month",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp (MMF Gov+CP ETFs)",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="USD",
                        target_percent=33.33,
                        currency="USD",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                            AllocationSeed(
                                name="Gov",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds Gov 3-month",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp (MMF Gov+CP ETFs)",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                        ],
                    ),
                ],
            ),
            AllocationSeed(
                name="Medical",
                target_percent=16.67,
                include=False,
                children=[
                    AllocationSeed(
                        name="UAH card balance, %",
                        target_percent=33.33,
                        currency="UAH",
                        include=True,
                    ),
                    AllocationSeed(
                        name="EUR",
                        target_percent=33.33,
                        currency="EUR",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                            AllocationSeed(
                                name="MMF Gov ETFs",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                            AllocationSeed(
                                name="MMF Gov+CP ETFs",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="USD",
                        target_percent=33.33,
                        currency="USD",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                            AllocationSeed(
                                name="MMF Gov ETFs",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                            AllocationSeed(
                                name="MMF Gov+CP ETFs",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                        ],
                    ),
                ],
            ),
            AllocationSeed(
                name="Auto",
                target_percent=16.67,
                include=False,
                notes="Split between fast access and longer-term repairs.",
                children=[
                    AllocationSeed(
                        name="40% split",
                        target_percent=40.0,
                        include=False,
                        children=[
                            AllocationSeed(
                                name="UAH card balance, %",
                                target_percent=33.33,
                                currency="UAH",
                                include=True,
                            ),
                            AllocationSeed(
                                name="EUR",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="USD",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="60% split",
                        target_percent=60.0,
                        include=False,
                        children=[
                            AllocationSeed(
                                name="UAH OVDP (1Y)",
                                target_percent=33.33,
                                currency="UAH",
                                include=True,
                            ),
                            AllocationSeed(
                                name="EUR",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="Gov",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=False,
                                        children=[
                                            AllocationSeed(
                                                name="MMF Gov ETFs",
                                                target_percent=50.0,
                                                currency="EUR",
                                                include=True,
                                            ),
                                            AllocationSeed(
                                                name="Bonds ladder (3M-1Y)",
                                                target_percent=50.0,
                                                currency="EUR",
                                                include=True,
                                            ),
                                        ],
                                    ),
                                    AllocationSeed(
                                        name="Corp",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=False,
                                        children=[
                                            AllocationSeed(
                                                name="MMF Gov+CP ETFs",
                                                target_percent=33.33,
                                                currency="EUR",
                                                include=True,
                                            ),
                                            AllocationSeed(
                                                name="ETF corp papers (<1Y)",
                                                target_percent=33.33,
                                                currency="EUR",
                                                include=True,
                                            ),
                                            AllocationSeed(
                                                name="Rate-hedged ETF",
                                                target_percent=33.33,
                                                currency="EUR",
                                                include=True,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="USD",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="Gov",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=False,
                                        children=[
                                            AllocationSeed(
                                                name="MMF Gov ETFs",
                                                target_percent=50.0,
                                                currency="USD",
                                                include=True,
                                            ),
                                            AllocationSeed(
                                                name="Bonds ladder (3M-1Y)",
                                                target_percent=50.0,
                                                currency="USD",
                                                include=True,
                                            ),
                                        ],
                                    ),
                                    AllocationSeed(
                                        name="Corp",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=False,
                                        children=[
                                            AllocationSeed(
                                                name="MMF Gov+CP ETFs",
                                                target_percent=33.33,
                                                currency="USD",
                                                include=True,
                                            ),
                                            AllocationSeed(
                                                name="ETF corp papers (<1Y)",
                                                target_percent=33.33,
                                                currency="USD",
                                                include=True,
                                            ),
                                            AllocationSeed(
                                                name="Rate-hedged ETF",
                                                target_percent=33.33,
                                                currency="USD",
                                                include=True,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    ),
    AllocationSeed(
        name="Savings",
        target_percent=16.67,
        include=False,
        notes="Savings for near-term goals.",
        children=[
            AllocationSeed(
                name="Short goal (<1Y)",
                target_percent=20.0,
                include=False,
                children=[
                    AllocationSeed(
                        name="UAH",
                        target_percent=33.33,
                        currency="UAH",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                            ),
                            AllocationSeed(
                                name="OVDP (1Y)",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="EUR",
                        target_percent=33.33,
                        currency="EUR",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                            AllocationSeed(
                                name="Gov",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds ladder (3M-1Y)",
                                        target_percent=50.0,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ETF corp papers (<1Y)",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Rate-hedged ETF",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="USD",
                        target_percent=33.33,
                        currency="USD",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                            AllocationSeed(
                                name="Gov",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds ladder (3M-1Y)",
                                        target_percent=50.0,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ETF corp papers (<1Y)",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Rate-hedged ETF",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            AllocationSeed(
                name="Long goal (<30Y)",
                target_percent=20.0,
                include=False,
                children=[
                    AllocationSeed(
                        name="UAH",
                        target_percent=33.33,
                        currency="UAH",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                            ),
                            AllocationSeed(
                                name="OVDP (1Y-3Y)",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="EUR",
                        target_percent=33.33,
                        currency="EUR",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="EUR",
                                include=True,
                            ),
                            AllocationSeed(
                                name="Gov",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds ladder (3M-30Y)",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ILB ladder",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp",
                                target_percent=33.33,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ETF corp papers",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Rate-hedged ETF",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="USD",
                        target_percent=33.33,
                        currency="USD",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=33.33,
                                currency="USD",
                                include=True,
                            ),
                            AllocationSeed(
                                name="Gov",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds ladder (3M-30Y)",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="TIPS ladder",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp",
                                target_percent=33.33,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ETF corp papers",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Rate-hedged ETF",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    ),
    AllocationSeed(
        name="Investments",
        target_percent=16.67,
        include=False,
        notes="Long-term investment allocations.",
        children=[
            AllocationSeed(
                name="Fixed term",
                target_percent=50.0,
                include=False,
                children=[
                    AllocationSeed(
                        name="UAH",
                        target_percent=33.33,
                        currency="UAH",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Card balance, %",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                            ),
                            AllocationSeed(
                                name="OVDP (1Y-3Y)",
                                target_percent=50.0,
                                currency="UAH",
                                include=True,
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="EUR",
                        target_percent=33.33,
                        currency="EUR",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Gov",
                                target_percent=50.0,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds ladder (3M-30Y)",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ILB ladder",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp",
                                target_percent=50.0,
                                currency="EUR",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ETF corp papers",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Rate-hedged ETF",
                                        target_percent=33.33,
                                        currency="EUR",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    AllocationSeed(
                        name="USD",
                        target_percent=33.33,
                        currency="USD",
                        include=False,
                        children=[
                            AllocationSeed(
                                name="Gov",
                                target_percent=50.0,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov ETFs",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Bonds ladder (3M-30Y)",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="TIPS ladder",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                            AllocationSeed(
                                name="Corp",
                                target_percent=50.0,
                                currency="USD",
                                include=False,
                                children=[
                                    AllocationSeed(
                                        name="MMF Gov+CP ETFs",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="ETF corp papers",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                    AllocationSeed(
                                        name="Rate-hedged ETF",
                                        target_percent=33.33,
                                        currency="USD",
                                        include=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            AllocationSeed(
                name="Stocks and crypto",
                target_percent=50.0,
                include=True,
                notes="Higher risk, higher reward portion of the investment bucket.",
            ),
        ],
    ),
]


def populate_with_sample_data(repo: AllocationRepository, *, replace: bool = False) -> None:
    """Insert the sample allocation tree into the repository."""

    if replace:
        repo.clear_all()

    def _populate(seed: AllocationSeed, parent_id: Optional[int]) -> None:
        allocation = seed.as_allocation(repo, parent_id)
        new_id = repo.add_allocation(allocation)
        for child in seed.children or []:
            _populate(child, new_id)

    for top_level in SAMPLE_ALLOCATIONS:
        _populate(top_level, None)
