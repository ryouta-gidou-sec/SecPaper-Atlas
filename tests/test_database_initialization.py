"""Physical initialization invariants, using synthetic temporary databases only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3

import pytest

from src.database import Database, LABEL_TABLES, SCHEMA
from src.models import ClassificationResult, ExtractedMetadata


EDITABLE_VALUES = {
    "primary_category": "Session Management",
    "relevance": "A",
    "relevance_reason": "Synthetic AI reason.",
    "relevance_confidence": 0.91,
}


def _create_database(path: Path) -> Database:
    database = Database(path)
    with database.connect() as connection:
        connection.executescript(SCHEMA)
    return database


def _add_classified(database: Database, file_hash: str = "a" * 64) -> int:
    return database.add_paper(
        file_hash=file_hash, filename="synthetic.pdf", filepath="synthetic.pdf",
        metadata=ExtractedMetadata(title="Synthetic session security study"),
        classification=ClassificationResult(
            **EDITABLE_VALUES, tags=["AI tag"], research_methods=["AI method"],
            target_vulnerabilities=["AI vulnerability"],
        ),
        classification_provider="local", classification_model="synthetic-model",
    )


def _state(database: Database) -> dict:
    # All connections are closed before reading bytes/stat. The snapshot includes
    # schema, every data/history row and sqlite_sequence, through a read-only handle.
    with database.connect_readonly() as connection:
        logical = database.snapshot(connection)
    raw = database.path.read_bytes()
    stat = database.path.stat()
    assert raw[:16] == b"SQLite format 3\x00"
    return {
        "bytes": raw, "sha256": hashlib.sha256(raw).hexdigest(),
        "size": stat.st_size, "counter": int.from_bytes(raw[24:28], "big"),
        "mtime_ns": stat.st_mtime_ns, "logical": logical,
    }


def _assert_repeated_initialize(database: Database, repetitions: int = 4) -> None:
    # A deliberately old mtime avoids sleeps and filesystem timestamp resolution
    # races. Compare the timestamp actually stored by this filesystem.
    os.utime(database.path, ns=(946684800000000000, 946684800000000000))
    baseline = _state(database)
    for _ in range(repetitions):
        database.initialize()
        assert _state(database) == baseline


@pytest.mark.parametrize("populated", [False, True], ids=["empty", "populated"])
def test_initialize_is_physically_idempotent(tmp_path: Path, populated: bool) -> None:
    database = _create_database(tmp_path / "current.db")
    if populated:
        paper_id = _add_classified(database)
        database.update_classification(
            paper_id, None, classification_status="failed",
            classification_error="Synthetic provider failure",
            classification_provider="local", classification_model="synthetic-model",
        )
        _add_classified(database, "b" * 64)
        database.add_paper(
            file_hash="c" * 64, filename="pending.pdf", filepath="pending.pdf",
            metadata=ExtractedMetadata(title="Synthetic pending study"),
            classification=None, classification_error="API key is not configured",
        )
        database.add_paper(
            file_hash="d" * 64, filename="review.pdf", filepath="review.pdf",
            metadata=ExtractedMetadata(title="Synthetic held study", review_reasons=["No abstract"]),
            classification=None,
        )
    before = _state(database)
    database.initialize()
    assert _state(database) == before
    _assert_repeated_initialize(database)


@pytest.mark.parametrize("field", [*EDITABLE_VALUES, "all"])
def test_initialize_clears_only_non_null_legacy_projections(
    tmp_path: Path, field: str,
) -> None:
    database = _create_database(tmp_path / "projected.db")
    paper_id = _add_classified(database)
    fields = list(EDITABLE_VALUES) if field == "all" else [field]
    with database.connect() as connection:
        connection.execute(
            "UPDATE papers SET " + ", ".join(f"{name} = ?" for name in fields) + " WHERE id = ?",
            (*[EDITABLE_VALUES[name] for name in fields], paper_id),
        )
    before = _state(database)
    database.initialize()
    after = _state(database)
    assert after["bytes"] != before["bytes"]
    assert after["counter"] > before["counter"]
    expected = before["logical"]
    for name in EDITABLE_VALUES:
        expected["tables"]["papers"][0][name] = None
    assert after["logical"] == expected  # AI originals, labels and history unchanged.
    _assert_repeated_initialize(database)


@pytest.mark.parametrize("label_key", list(LABEL_TABLES))
def test_initialize_removes_legacy_current_labels_once(tmp_path: Path, label_key: str) -> None:
    database = _create_database(tmp_path / "labels.db")
    paper_id = _add_classified(database)
    _, junction, foreign_key = LABEL_TABLES[label_key]
    with database.connect() as connection:
        connection.execute(
            f"INSERT INTO {junction} (paper_id, {foreign_key}, value_source) "
            f"SELECT paper_id, {foreign_key}, 'current' FROM {junction} WHERE paper_id = ?",
            (paper_id,),
        )
    before = _state(database)
    database.initialize()
    after = _state(database)
    assert after["bytes"] != before["bytes"]
    assert after["counter"] > before["counter"]
    expected = before["logical"]
    expected["tables"][junction] = [
        row for row in expected["tables"][junction] if row["value_source"] == "ai"
    ]
    assert after["logical"] == expected
    _assert_repeated_initialize(database)


def test_initialize_preserves_reviewed_values_and_all_history(tmp_path: Path) -> None:
    database = _create_database(tmp_path / "reviewed.db")
    paper_id = _add_classified(database)
    database.update_review(
        paper_id, primary_category="Authorization", relevance="B",
        relevance_reason="Synthetic human reason.", status="Read",
        tags=["Human tag"], research_methods=["Human method"],
        target_vulnerabilities=["Human vulnerability"],
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE papers SET relevance_confidence = ? WHERE id = ?", (0.5, paper_id),
        )
    database.update_classification(
        paper_id, None, classification_status="failed",
        classification_error="Synthetic failure after review",
        classification_provider="openai", classification_model="synthetic-retry",
    )
    # Include an unreviewed row so preservation is exercised alongside the cleanup.
    _add_classified(database, "b" * 64)
    before = _state(database)
    assert len(before["logical"]["tables"]["classification_runs"]) == 3
    database.initialize()
    assert _state(database) == before
    _assert_repeated_initialize(database)


def test_initialize_migrates_old_schema_and_backfills_history_once(tmp_path: Path) -> None:
    path = tmp_path / "old-schema.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, file_hash TEXT NOT NULL UNIQUE,
                primary_category TEXT, relevance TEXT, status TEXT, year INTEGER,
                ai_primary_category TEXT, classification_error TEXT
            )"""
        )
        connection.executemany(
            """INSERT INTO papers (file_hash, status, ai_primary_category,
               primary_category, relevance, classification_error) VALUES (?, ?, ?, ?, ?, ?)""",
            [
                ("a" * 64, "Unread", "Authentication", "Authentication", "A", None),
                ("b" * 64, "Unread", None, None, None, "Synthetic provider failure"),
                ("c" * 64, "Unread", None, None, None, "API key is not configured"),
            ],
        )
    raw_before = path.read_bytes()
    database = Database(path)
    database.initialize()
    after = _state(database)
    assert after["bytes"] != raw_before
    assert after["counter"] > int.from_bytes(raw_before[24:28], "big")
    with database.connect_readonly() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(papers)")}
    assert {
        "introduction_excerpt", "metadata_review_reasons_json", "classification_status",
        "manually_reviewed", "classification_provider", "classification_model", "classified_at",
    } <= columns
    rows = after["logical"]["tables"]["papers"]
    assert [row["classification_status"] for row in rows] == ["classified", "failed", "pending"]
    assert rows[0]["ai_primary_category"] == "Authentication"
    assert rows[0]["primary_category"] is None
    assert rows[0]["relevance"] is None
    history = database.classification_history(rows[0]["id"])
    assert len(history) == 1
    assert history[0]["result"]["primary_category"] == "Authentication"
    assert history[0]["provider"] is None
    assert history[0]["model"] is None
    assert history[0]["classified_at"] is None
    _assert_repeated_initialize(database)
