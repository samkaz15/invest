"""Migration runner: db/migrations/*.sql applied in filename order.

Each file runs inside one transaction together with its bookkeeping row —
a half-applied migration cannot be recorded as applied. Migrations are
append-only and backward compatible (MSD preamble); editing an applied
file is forbidden.
"""

from pathlib import Path

from bios.common.logutil import get_logger
from bios.storage.db import Database, StorageError

logger = get_logger(__name__)

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationRunner:
    def __init__(self, db: Database, migrations_dir: Path) -> None:
        self._db = db
        self._dir = migrations_dir

    def applied(self) -> set[str]:
        self._db.execute(_BOOTSTRAP)
        return {r["version"] for r in self._db.query("SELECT version FROM schema_migrations")}

    def pending(self) -> list[Path]:
        done = self.applied()
        return [p for p in sorted(self._dir.glob("*.sql")) if p.stem not in done]

    def apply_all(self) -> list[str]:
        applied: list[str] = []
        for path in self.pending():
            sql = path.read_text(encoding="utf-8")
            try:
                with self._db.transaction() as conn:
                    conn.execute(sql)  # multi-statement DDL (simple query protocol)
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%(v)s)",
                        {"v": path.stem},
                    )
            except StorageError:
                raise
            except Exception as exc:  # psycopg errors carry the failing statement
                raise StorageError(f"migration {path.name} failed: {exc}") from exc
            logger.info("applied migration %s", path.name)
            applied.append(path.stem)
        return applied
