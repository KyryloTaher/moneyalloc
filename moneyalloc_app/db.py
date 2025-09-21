"""Database helpers for the Money Allocation application."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional
import sqlite3

from .models import Allocation, Distribution, DistributionEntry

DB_FILENAME = "allocations.db"


class AllocationRepository:
    """Simple SQLite-backed repository for allocation nodes."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parent / DB_FILENAME
        self.db_path = db_path
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id INTEGER REFERENCES allocations(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    currency TEXT,
                    instrument TEXT,
                    target_percent REAL NOT NULL DEFAULT 0.0,
                    include_in_rollup INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    current_value REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_allocations_parent
                    ON allocations(parent_id, sort_order, id)
                """
            )
            # Ensure the table carries the new column when upgrading from older versions.
            info = conn.execute("PRAGMA table_info(allocations)").fetchall()
            columns = {row[1] for row in info}
            if "instrument" not in columns:
                conn.execute("ALTER TABLE allocations ADD COLUMN instrument TEXT")
            if "current_value" not in columns:
                conn.execute(
                    "ALTER TABLE allocations ADD COLUMN current_value REAL NOT NULL DEFAULT 0.0"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS distributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    tolerance_percent REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS distribution_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    distribution_id INTEGER NOT NULL REFERENCES distributions(id) ON DELETE CASCADE,
                    allocation_id INTEGER NOT NULL REFERENCES allocations(id) ON DELETE CASCADE,
                    allocation_path TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    target_share REAL NOT NULL,
                    current_value REAL NOT NULL,
                    current_share REAL NOT NULL,
                    target_value REAL NOT NULL,
                    recommended_change REAL NOT NULL,
                    share_diff REAL NOT NULL,
                    action TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------
    def get_all_allocations(self) -> List[Allocation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM allocations ORDER BY parent_id IS NOT NULL, parent_id, sort_order, id"
            ).fetchall()
        return [self._row_to_allocation(row) for row in rows]

    def get_allocation(self, allocation_id: int) -> Optional[Allocation]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM allocations WHERE id = ?",
                (allocation_id,),
            ).fetchone()
        return self._row_to_allocation(row) if row else None

    def get_children(self, parent_id: Optional[int]) -> List[Allocation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM allocations WHERE parent_id IS ? ORDER BY sort_order, id",
                (parent_id,),
            ).fetchall()
        return [self._row_to_allocation(row) for row in rows]

    def get_next_sort_order(self, parent_id: Optional[int]) -> int:
        with self._connect() as conn:
            result = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM allocations WHERE parent_id IS ?",
                (parent_id,),
            ).fetchone()
        return int(result[0]) if result else 0

    def add_allocation(self, allocation: Allocation) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO allocations (
                    parent_id,
                    name,
                    currency,
                    instrument,
                    target_percent,
                    include_in_rollup,
                    notes,
                    sort_order,
                    current_value
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    allocation.parent_id,
                    allocation.name,
                    allocation.currency,
                    allocation.instrument,
                    allocation.target_percent,
                    1 if allocation.include_in_rollup else 0,
                    allocation.notes,
                    allocation.sort_order,
                    allocation.current_value,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_allocation(self, allocation: Allocation) -> None:
        if allocation.id is None:
            raise ValueError("Cannot update an allocation without an id")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE allocations
                SET parent_id = ?,
                    name = ?,
                    currency = ?,
                    instrument = ?,
                    target_percent = ?,
                    include_in_rollup = ?,
                    notes = ?,
                    sort_order = ?,
                    current_value = ?
                WHERE id = ?
                """,
                (
                    allocation.parent_id,
                    allocation.name,
                    allocation.currency,
                    allocation.instrument,
                    allocation.target_percent,
                    1 if allocation.include_in_rollup else 0,
                    allocation.notes,
                    allocation.sort_order,
                    allocation.current_value,
                    allocation.id,
                ),
            )
            conn.commit()

    def delete_allocation(self, allocation_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM allocations WHERE id = ?", (allocation_id,))
            conn.commit()

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM allocations")
            conn.commit()

    def bulk_insert(self, items: Iterable[Allocation]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO allocations (
                    id,
                    parent_id,
                    name,
                    currency,
                    instrument,
                    target_percent,
                    include_in_rollup,
                    notes,
                    sort_order,
                    current_value
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.parent_id,
                        item.name,
                        item.currency,
                        item.instrument,
                        item.target_percent,
                        1 if item.include_in_rollup else 0,
                        item.notes,
                        item.sort_order,
                        item.current_value,
                    )
                    for item in items
                ],
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_allocation(row: sqlite3.Row) -> Allocation:
        return Allocation(
            id=int(row["id"]),
            parent_id=row["parent_id"],
            name=row["name"],
            currency=row["currency"],
            instrument=row["instrument"],
            target_percent=float(row["target_percent"] or 0.0),
            include_in_rollup=bool(row["include_in_rollup"]),
            notes=row["notes"] or "",
            sort_order=int(row["sort_order"] or 0),
            current_value=float(row["current_value"] or 0.0),
        )

    # ------------------------------------------------------------------
    # Distribution helpers
    # ------------------------------------------------------------------
    def create_distribution(
        self, distribution: Distribution, entries: Iterable[DistributionEntry]
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO distributions (name, total_amount, tolerance_percent, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    distribution.name,
                    distribution.total_amount,
                    distribution.tolerance_percent,
                    distribution.created_at,
                ),
            )
            distribution_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO distribution_entries (
                    distribution_id,
                    allocation_id,
                    allocation_path,
                    currency,
                    target_share,
                    current_value,
                    current_share,
                    target_value,
                    recommended_change,
                    share_diff,
                    action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        distribution_id,
                        entry.allocation_id,
                        entry.allocation_path,
                        entry.currency,
                        entry.target_share,
                        entry.current_value,
                        entry.current_share,
                        entry.target_value,
                        entry.recommended_change,
                        entry.share_diff,
                        entry.action,
                    )
                    for entry in entries
                ],
            )
            conn.commit()
        return distribution_id

    def get_distributions(self) -> List[Distribution]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM distributions ORDER BY datetime(created_at) DESC, id DESC"
            ).fetchall()
        return [self._row_to_distribution(row) for row in rows]

    def get_distribution_entries(self, distribution_id: int) -> List[DistributionEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM distribution_entries
                WHERE distribution_id = ?
                ORDER BY allocation_path, id
                """,
                (distribution_id,),
            ).fetchall()
        return [self._row_to_distribution_entry(row) for row in rows]

    def delete_distribution(self, distribution_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM distributions WHERE id = ?", (distribution_id,))
            conn.commit()

    @staticmethod
    def _row_to_distribution(row: sqlite3.Row) -> Distribution:
        return Distribution(
            id=int(row["id"]),
            name=row["name"],
            total_amount=float(row["total_amount"] or 0.0),
            tolerance_percent=float(row["tolerance_percent"] or 0.0),
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_distribution_entry(row: sqlite3.Row) -> DistributionEntry:
        return DistributionEntry(
            id=int(row["id"]),
            distribution_id=int(row["distribution_id"]),
            allocation_id=int(row["allocation_id"]),
            allocation_path=row["allocation_path"],
            currency=row["currency"],
            target_share=float(row["target_share"] or 0.0),
            current_value=float(row["current_value"] or 0.0),
            current_share=float(row["current_share"] or 0.0),
            target_value=float(row["target_value"] or 0.0),
            recommended_change=float(row["recommended_change"] or 0.0),
            share_diff=float(row["share_diff"] or 0.0),
            action=row["action"],
        )


__all__ = [
    "AllocationRepository",
    "DB_FILENAME",
]
