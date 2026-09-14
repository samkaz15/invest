"""Small JSON state files (scheduler last-runs, breaker states, etags).

Operational state only — never domain data. Atomic writes (tmp + rename)
so a crash mid-save cannot corrupt state.
"""

import json
import os
from pathlib import Path
from typing import Any

from mios.common.errors import MiosError


class JsonStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise MiosError(f"corrupt or unreadable state file {self._path}: {exc}") from exc
        if not isinstance(data, dict):
            raise MiosError(f"state file {self._path} must hold a JSON object")
        return data

    def save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), "utf-8")
        os.replace(tmp, self._path)
