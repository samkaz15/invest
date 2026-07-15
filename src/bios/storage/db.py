"""Database access: thin wrapper over psycopg3, no ORM (ADR-009).

One connection per unit of work — collection cadence is minutes, not
milliseconds, so a pool is deliberate over-engineering (Constitution Art.8).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row

from bios.common.errors import BiosError


class StorageError(BiosError):
    """Database-level failure."""


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection[DictRow]]:
        """One transaction: commits on clean exit, rolls back on exception."""
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
                yield conn
        except psycopg.OperationalError as exc:
            raise StorageError(f"cannot reach database: {exc}") from exc
        except psycopg.Error as exc:
            # constraint violations, append-only triggers, bad SQL — all
            # surface as StorageError so callers never depend on psycopg
            raise StorageError(f"database error: {exc}") from exc

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.transaction() as conn:
            rows = conn.execute(sql, params or {}).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        with self.transaction() as conn:
            conn.execute(sql, params or {})

    def ping(self) -> bool:
        try:
            self.query("SELECT 1 AS ok")
            return True
        except StorageError:
            return False
