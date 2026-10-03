from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from src.database import Database


@pytest.fixture(autouse=True)
def isolated_application_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep default app settings and cached services away from personal data."""
    import streamlit as st

    monkeypatch.setattr("src.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "default-test.db"))
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.fixture
def database(tmp_path: Path) -> Database:
    instance = Database(tmp_path / "papers.db")
    instance.initialize()
    return instance
