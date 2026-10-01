from __future__ import annotations

from pathlib import Path

import pytest

from src.database import Database


@pytest.fixture
def database(tmp_path: Path) -> Database:
    instance = Database(tmp_path / "papers.db")
    instance.initialize()
    return instance
