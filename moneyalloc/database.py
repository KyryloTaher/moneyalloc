"""Database utilities for the Moneyalloc application."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


DB_FILENAME = "moneyalloc.db"


@dataclass
class AllocationRecord:
    id: int
    parent_id: Optional[int]
    name: str
    percentage: float
    currencies: str
    time_horizon: Optional[float]
    is_leaf: bool


@dataclass
class BucketRecord:
    bucket_key: str
    time_horizon: float
    currency: str
    percentage: float


@dataclass
class TenorInputRecord:
    bucket_key: str
    dv01_tenors: str
    bei01_tenors: str
    cs01_tenors: str


@dataclass
class ResultRecord:
    bucket_key: str
    amount: float
    dv01_tenor: float
    bei01_tenor: float
    cs01_tenor: float
    dv01_exposure: float


@dataclass
class PortfolioRecord:
    id: int
    name: str
    created_at: str


@dataclass
class PortfolioPosition:
    portfolio_id: int
    risk_group: str
    currency: str
    tenor: float
    amount: float


class Database:
    """Simple wrapper around SQLite operations."""

    def __init__(self, path: str | Path = DB_FILENAME) -> None:
        self.db_path = Path(path)
        self._ensure_initialised()

    def _ensure_initialised(self) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id INTEGER REFERENCES allocations(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    percentage REAL NOT NULL,
                    currencies TEXT DEFAULT '',
                    time_horizon REAL,
                    is_leaf INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS buckets (
                    bucket_key TEXT PRIMARY KEY,
                    time_horizon REAL NOT NULL,
                    currency TEXT NOT NULL,
                    percentage REAL NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tenor_inputs (
                    bucket_key TEXT PRIMARY KEY,
                    dv01_tenors TEXT DEFAULT '',
                    bei01_tenors TEXT DEFAULT '',
                    cs01_tenors TEXT DEFAULT ''
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    bucket_key TEXT PRIMARY KEY,
                    amount REAL NOT NULL,
                    dv01_tenor REAL NOT NULL,
                    bei01_tenor REAL NOT NULL,
                    cs01_tenor REAL NOT NULL,
                    dv01_exposure REAL NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_positions (
                    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
                    risk_group TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    tenor REAL NOT NULL,
                    amount REAL NOT NULL,
                    PRIMARY KEY (portfolio_id, risk_group, currency, tenor)
                )
                """
            )
            conn.commit()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.commit()
            conn.close()

    # Allocation operations -------------------------------------------------
    def add_allocation(
        self,
        *,
        parent_id: Optional[int],
        name: str,
        percentage: float,
        currencies: str,
        time_horizon: Optional[float],
        is_leaf: bool,
    ) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO allocations (parent_id, name, percentage, currencies, time_horizon, is_leaf)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (parent_id, name, percentage, currencies, time_horizon, int(is_leaf)),
            )
            allocation_id = cursor.lastrowid
            return allocation_id

    def update_allocation(
        self,
        allocation_id: int,
        *,
        name: str,
        percentage: float,
        currencies: str,
        time_horizon: Optional[float],
        is_leaf: bool,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE allocations
                SET name = ?, percentage = ?, currencies = ?, time_horizon = ?, is_leaf = ?
                WHERE id = ?
                """,
                (name, percentage, currencies, time_horizon, int(is_leaf), allocation_id),
            )

    def delete_allocation(self, allocation_id: int) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM allocations WHERE id = ?", (allocation_id,))

    def get_allocations(self) -> List[AllocationRecord]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, parent_id, name, percentage, currencies, time_horizon, is_leaf FROM allocations"
            )
            rows = cursor.fetchall()
        return [
            AllocationRecord(
                id=row[0],
                parent_id=row[1],
                name=row[2],
                percentage=row[3],
                currencies=row[4] or "",
                time_horizon=row[5],
                is_leaf=bool(row[6]),
            )
            for row in rows
        ]

    # Bucket operations -----------------------------------------------------
    def clear_buckets(self) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM buckets")

    def save_buckets(self, buckets: Iterable[BucketRecord]) -> None:
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO buckets (bucket_key, time_horizon, currency, percentage)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (bucket.bucket_key, bucket.time_horizon, bucket.currency, bucket.percentage)
                    for bucket in buckets
                ],
            )

    def get_buckets(self) -> List[BucketRecord]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT bucket_key, time_horizon, currency, percentage FROM buckets ORDER BY time_horizon, currency"
            )
            rows = cursor.fetchall()
        return [
            BucketRecord(
                bucket_key=row[0],
                time_horizon=row[1],
                currency=row[2],
                percentage=row[3],
            )
            for row in rows
        ]

    # Tenor inputs ----------------------------------------------------------
    def save_tenor_input(
        self,
        bucket_key: str,
        *,
        dv01_tenors: str,
        bei01_tenors: str,
        cs01_tenors: str,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO tenor_inputs (bucket_key, dv01_tenors, bei01_tenors, cs01_tenors)
                VALUES (?, ?, ?, ?)
                """,
                (bucket_key, dv01_tenors, bei01_tenors, cs01_tenors),
            )

    def get_tenor_inputs(self) -> Dict[str, TenorInputRecord]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT bucket_key, dv01_tenors, bei01_tenors, cs01_tenors FROM tenor_inputs")
            rows = cursor.fetchall()
        return {
            row[0]: TenorInputRecord(
                bucket_key=row[0],
                dv01_tenors=row[1] or "",
                bei01_tenors=row[2] or "",
                cs01_tenors=row[3] or "",
            )
            for row in rows
        }

    # Settings --------------------------------------------------------------
    def set_setting(self, key: str, value: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_setting(self, key: str) -> Optional[str]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
        return row[0] if row else None

    # Results ---------------------------------------------------------------
    def clear_results(self) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM results")

    def save_results(self, results: Iterable[ResultRecord]) -> None:
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO results (bucket_key, amount, dv01_tenor, bei01_tenor, cs01_tenor, dv01_exposure)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.bucket_key,
                        result.amount,
                        result.dv01_tenor,
                        result.bei01_tenor,
                        result.cs01_tenor,
                        result.dv01_exposure,
                    )
                    for result in results
                ],
            )

    def get_results(self) -> List[ResultRecord]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT bucket_key, amount, dv01_tenor, bei01_tenor, cs01_tenor, dv01_exposure FROM results"
            )
            rows = cursor.fetchall()
        return [
            ResultRecord(
                bucket_key=row[0],
                amount=row[1],
                dv01_tenor=row[2],
                bei01_tenor=row[3],
                cs01_tenor=row[4],
                dv01_exposure=row[5],
            )
            for row in rows
        ]

    # Portfolio history ----------------------------------------------------
    def save_portfolio(
        self,
        name: str,
        positions: Dict[Tuple[str, str, float], float],
    ) -> int:
        timestamp = datetime.utcnow().isoformat(timespec="seconds")
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO portfolios (name, created_at) VALUES (?, ?)",
                (name, timestamp),
            )
            portfolio_id = cursor.lastrowid
            cursor.executemany(
                """
                INSERT INTO portfolio_positions (portfolio_id, risk_group, currency, tenor, amount)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (portfolio_id, risk_group, currency, tenor, amount)
                    for (risk_group, currency, tenor), amount in positions.items()
                ],
            )
            return int(portfolio_id)

    def list_portfolios(self) -> List[PortfolioRecord]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, created_at FROM portfolios ORDER BY datetime(created_at) DESC"
            )
            rows = cursor.fetchall()
        return [PortfolioRecord(id=row[0], name=row[1], created_at=row[2]) for row in rows]

    def get_portfolio_positions(
        self, portfolio_id: int
    ) -> Dict[Tuple[str, str, float], float]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT risk_group, currency, tenor, amount
                FROM portfolio_positions
                WHERE portfolio_id = ?
                """,
                (portfolio_id,),
            )
            rows = cursor.fetchall()
        return {
            (row[0], row[1], row[2]): row[3]
            for row in rows
        }

    def get_latest_portfolio(self) -> Optional[PortfolioRecord]:
        portfolios = self.list_portfolios()
        return portfolios[0] if portfolios else None

