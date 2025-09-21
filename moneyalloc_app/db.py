"""Database helpers for the Money Allocation application."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional
import sqlite3

from .models import Allocation

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
                    target_percent REAL NOT NULL DEFAULT 0.0,
                    include_in_rollup INTEGER NOT NULL DEFAULT 1,
                    notes TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_allocations_parent
                    ON allocations(parent_id, sort_order, id)
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
                INSERT INTO allocations (parent_id, name, currency, target_percent, include_in_rollup, notes, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    allocation.parent_id,
                    allocation.name,
                    allocation.currency,
                    allocation.target_percent,
                    1 if allocation.include_in_rollup else 0,
                    allocation.notes,
                    allocation.sort_order,
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
                    target_percent = ?,
                    include_in_rollup = ?,
                    notes = ?,
                    sort_order = ?
                WHERE id = ?
                """,
                (
                    allocation.parent_id,
                    allocation.name,
                    allocation.currency,
                    allocation.target_percent,
                    1 if allocation.include_in_rollup else 0,
                    allocation.notes,
                    allocation.sort_order,
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
                INSERT INTO allocations (id, parent_id, name, currency, target_percent, include_in_rollup, notes, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.id,
                        item.parent_id,
                        item.name,
                        item.currency,
                        item.target_percent,
                        1 if item.include_in_rollup else 0,
                        item.notes,
                        item.sort_order,
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
            target_percent=float(row["target_percent"] or 0.0),
            include_in_rollup=bool(row["include_in_rollup"]),
            notes=row["notes"] or "",
            sort_order=int(row["sort_order"] or 0),
        )


__all__ = ["AllocationRepository", "DB_FILENAME"]
