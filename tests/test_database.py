from __future__ import annotations

import sqlite3

import pytest

from src.database import Database, DuplicatePaperError
from src.models import ClassificationResult, ExtractedMetadata


def classification() -> ClassificationResult:
    return ClassificationResult(
        primary_category="Session Management",
        tags=["Session Hijacking", "Cookie Security"],
        research_methods=["Black-box Testing"],
        target_vulnerabilities=["Session Hijacking"],
        relevance="A",
        relevance_reason="Strong match for the current research focus.",
        relevance_confidence=0.91,
    )


def add_sample(database: Database, file_hash: str = "a" * 64) -> int:
    return database.add_paper(
        file_hash=file_hash,
        filename="paper.pdf",
        filepath="C:/papers/paper.pdf",
        metadata=ExtractedMetadata(
            title="Automated Session Hijacking Detection",
            authors=["Researcher One"],
            year=2025,
            abstract="A browser-based black-box study.",
            keywords=["session", "security"],
        ),
        classification=classification(),
    )


def test_database_registration_and_duplicate_detection(database: Database) -> None:
    paper_id = add_sample(database)
    assert database.paper_exists("a" * 64)
    paper = database.get_paper(paper_id)
    assert paper["primary_category"] is None
    assert paper["relevance"] is None
    assert paper["tags"] == []
    assert paper["ai_primary_category"] == "Session Management"
    assert paper["ai_tags"] == ["Cookie Security", "Session Hijacking"]
    assert paper["effective_primary_category"] == "Session Management"
    assert paper["effective_tags"] == paper["ai_tags"]
    with pytest.raises(DuplicatePaperError):
        add_sample(database)


def test_database_searches_text_and_normalized_labels(database: Database) -> None:
    add_sample(database)
    assert len(database.search_papers(keyword="browser-based")) == 1
    assert len(database.search_papers(tags=["Cookie Security"])) == 1
    assert len(database.search_papers(methods=["Black-box Testing"])) == 1
    assert len(database.search_papers(vulnerabilities=["Session Hijacking"])) == 1
    assert database.search_papers(categories=["Authorization"]) == []


def test_manual_review_preserves_ai_values(database: Database) -> None:
    paper_id = add_sample(database)
    database.update_review(
        paper_id,
        primary_category="Vulnerability Assessment",
        tags=["Automated Detection", "Custom Portfolio Tag"],
        relevance="B",
        status="Important",
        research_methods=["Dynamic Analysis"],
        target_vulnerabilities=["Session Fixation"],
        relevance_reason="Useful, but less central after human review.",
    )
    database.initialize()
    paper = database.get_paper(paper_id)
    assert paper["primary_category"] == "Vulnerability Assessment"
    assert paper["ai_primary_category"] == "Session Management"
    assert paper["tags"] == ["Automated Detection", "Custom Portfolio Tag"]
    assert paper["ai_tags"] == ["Cookie Security", "Session Hijacking"]
    assert paper["research_methods"] == ["Dynamic Analysis"]
    assert paper["ai_research_methods"] == ["Black-box Testing"]
    assert paper["target_vulnerabilities"] == ["Session Fixation"]
    assert paper["ai_target_vulnerabilities"] == ["Session Hijacking"]
    assert paper["relevance_reason"] == "Useful, but less central after human review."
    assert paper["ai_relevance_reason"] == "Strong match for the current research focus."
    assert paper["manually_reviewed"] is True


def test_classification_retry_updates_only_ai_values(database: Database) -> None:
    paper_id = add_sample(database)
    database.update_review(
        paper_id,
        primary_category="Authorization",
        tags=["Human reviewed tag"],
        relevance="B",
        status="Unread",
        research_methods=["Human reviewed method"],
        target_vulnerabilities=["Human reviewed vulnerability"],
        relevance_reason="Human reviewed reason.",
    )
    replacement = ClassificationResult(
        primary_category="Vulnerability Assessment",
        tags=["AI replacement tag"],
        research_methods=["Dynamic Analysis"],
        target_vulnerabilities=["SQL Injection"],
        relevance="C",
        relevance_reason="A different AI classification.",
        relevance_confidence=0.55,
    )
    database.update_classification(
        paper_id, replacement, classification_status="classified"
    )

    paper = database.get_paper(paper_id)
    assert paper["ai_primary_category"] == "Vulnerability Assessment"
    assert paper["ai_tags"] == ["AI replacement tag"]
    assert paper["primary_category"] == "Authorization"
    assert paper["tags"] == ["Human reviewed tag"]
    assert paper["effective_primary_category"] == "Authorization"
    assert paper["effective_tags"] == ["Human reviewed tag"]


def test_database_persists_extraction_provenance_and_pending_state(database: Database) -> None:
    paper_id = database.add_paper(
        file_hash="b" * 64,
        filename="pending.pdf",
        filepath="C:/papers/pending.pdf",
        metadata=ExtractedMetadata(
            title="A Pending Paper About Session Security",
            introduction_excerpt="A bounded introduction excerpt for classification." * 4,
            metadata_sources={"title": "first page layout"},
            review_reasons=[],
        ),
        classification=None,
        classification_error="OPENAI_API_KEY is not configured",
    )
    paper = database.get_paper(paper_id)
    assert paper["classification_status"] == "pending"
    assert paper["introduction_excerpt"].startswith("A bounded")
    assert paper["metadata_sources"] == {"title": "first page layout"}
    assert paper["metadata_review_reasons"] == []
    assert len(database.search_papers(classification_statuses=["pending"])) == 1


def test_initialize_migrates_legacy_papers_table_without_losing_rows(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash TEXT NOT NULL UNIQUE,
                primary_category TEXT,
                relevance TEXT,
                status TEXT,
                year INTEGER,
                ai_primary_category TEXT,
                classification_error TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO papers (file_hash, status, ai_primary_category,
               primary_category, relevance) VALUES (?, ?, ?, ?, ?)""",
            ("c" * 64, "Unread", "Authentication", "Authentication", "A"),
        )
    migrated = Database(path)
    migrated.initialize()
    with migrated.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(papers)")}
        row = connection.execute("SELECT * FROM papers WHERE file_hash = ?", ("c" * 64,)).fetchone()
    assert {"introduction_excerpt", "metadata_review_reasons_json", "classification_status"} <= columns
    assert row["classification_status"] == "classified"
    assert "manually_reviewed" in columns
    assert row["manually_reviewed"] == 0
    assert row["primary_category"] is None
    assert row["relevance"] is None
