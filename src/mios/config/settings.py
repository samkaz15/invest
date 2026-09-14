"""Process-level runtime settings, read from environment / ``.env``.

Settings = *where things are and how the process behaves*.
YAML config (mios.config.loader) = *what the system knows and how it scores*.
Secrets only ever live here, never in YAML.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIOS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "prod"] = "dev"
    config_dir: Path = Path("config")
    # Operational, disposable state: scheduler last-runs, breaker states,
    # etags, health, DLQ, metrics. Git-ignored; safe to lose.
    var_dir: Path = Path("var")
    # Collected payloads, verbatim and permanent. Committed to the repository
    # (ADR-010: the database holds normalized truth; the raw files are what
    # let it be rebuilt), so this must NOT live under var_dir.
    data_dir: Path = Path("data")
    log_level: str = "INFO"
    log_json: bool = False
    database_url: str = "postgresql://localhost/mios"
    migrations_dir: Path = Path("db/migrations")

    @property
    def audit_dir(self) -> Path:
        """Directory for append-only audit sinks (git-ignored)."""
        return self.var_dir / "audit"

    @property
    def reports_dir(self) -> Path:
        """Generated reports. Committed: they are the human deliverable."""
        return Path("reports")

    @property
    def raw_dir(self) -> Path:
        """Raw store root: ``data/raw/<source_id>/<YYYY-MM>/<raw_item_id>.json``"""
        return self.data_dir / "raw"
