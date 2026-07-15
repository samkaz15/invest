"""Process-level runtime settings, read from environment / ``.env``.

Settings = *where things are and how the process behaves*.
YAML config (bios.config.loader) = *what the system knows and how it scores*.
Secrets only ever live here, never in YAML (RISK_AND_GOVERNANCE.md).
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BIOS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["dev", "prod"] = "dev"
    config_dir: Path = Path("config")
    var_dir: Path = Path("var")
    log_level: str = "INFO"
    log_json: bool = False
    database_url: str = "postgresql://localhost/bios"
    migrations_dir: Path = Path("db/migrations")
    seeds_dir: Path = Path("seeds/chains")

    @property
    def audit_dir(self) -> Path:
        """Directory for append-only audit sinks (git-ignored)."""
        return self.var_dir / "audit"
