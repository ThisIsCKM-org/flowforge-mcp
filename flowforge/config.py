from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FlowForgeConfig:
    db_path: Path

    @classmethod
    def from_env(cls) -> "FlowForgeConfig":
        return cls(db_path=Path(os.environ.get("FLOWFORGE_DB_PATH", "data/flowforge.db")))

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

