from __future__ import annotations

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
    assert database.get_paper(paper_id)["tags"] == ["Cookie Security", "Session Hijacking"]
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
