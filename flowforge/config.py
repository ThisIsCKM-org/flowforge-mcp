from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FlowForgeConfig:
    db_path: Path
    max_image_bytes: int = 10 * 1024 * 1024
    attachment_export_dir: Path = Path(tempfile.gettempdir()) / "flowforge-attachments"

    @classmethod
    def from_env(cls) -> "FlowForgeConfig":
        return cls(
            db_path=Path(os.environ.get("FLOWFORGE_DB_PATH", "data/flowforge.db")),
            max_image_bytes=int(os.environ.get("FLOWFORGE_MAX_IMAGE_BYTES", str(10 * 1024 * 1024))),
            attachment_export_dir=Path(
                os.environ.get("FLOWFORGE_ATTACHMENT_EXPORT_DIR", str(Path(tempfile.gettempdir()) / "flowforge-attachments"))
            ),
        )

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.attachment_export_dir.mkdir(parents=True, exist_ok=True)

