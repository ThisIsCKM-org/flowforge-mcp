from pathlib import Path

import pytest

from flowforge.service import FlowForgeService


@pytest.fixture
def service(tmp_path: Path) -> FlowForgeService:
    return FlowForgeService.for_path(tmp_path / "flowforge.db")
