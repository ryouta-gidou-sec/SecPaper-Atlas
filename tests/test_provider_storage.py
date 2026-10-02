import logging

import pytest
from pydantic import ValidationError

from src.classifier import ClassificationError
from src.models import ClassificationResult, ExtractedMetadata
from src.pdf_parser import ParsedPDF
from src.scanner import scan_inbox


def result(category="Authentication"):
    return ClassificationResult(
        primary_category=category, tags=["Authentication"], research_methods=["Empirical Study"],
        target_vulnerabilities=["Authentication Bypass"], relevance="B",
        relevance_reason="Authentication research is relevant.", relevance_confidence=0.8,
    )


def add(database, classification=None, **kwargs):
    return database.add_paper(
        file_hash="a" * 64, filename="fixture.pdf", filepath="fixture.pdf",
        metadata=ExtractedMetadata(title="A Paper About Authentication"),
        classification=classification, **kwargs,
    )


def test_provider_model_date_and_history_preserve_ai_and_human_values(database):
    paper_id = add(database, result(), classification_provider="local", classification_model="local-model")
    paper = database.get_paper(paper_id)
    assert paper["classification_provider"] == "local"
    assert paper["classification_model"] == "local-model"
    assert paper["classified_at"].endswith("Z")
    assert paper["primary_category"] is None
    assert paper["tags"] == []
    database.update_review(paper_id, primary_category="Session Management", tags=["Human tag"],
                           relevance="A", status="Read", research_methods=[], target_vulnerabilities=[])
    database.update_classification(paper_id, result("Authorization"), classification_status="classified",
                                   classification_provider="openai", classification_model="api-model")
    database.update_classification(paper_id, None, classification_status="failed",
                                   classification_error="Ollama request failed (ConnectError)",
                                   classification_provider="local", classification_model="other-model")
    database.initialize()
    paper = database.get_paper(paper_id)
    assert paper["classification_provider"] == "openai"  # belongs to latest successful AI
    assert paper["classification_status"] == "failed"
    assert paper["primary_category"] == "Session Management"
    assert paper["ai_primary_category"] == "Authorization"
    assert paper["tags"] == ["Human tag"]
    history = database.classification_history(paper_id)
    assert len(history) == 3
    assert history[0]["result"] == result().model_dump(mode="json")
    assert history[1]["result"]["primary_category"] == "Authorization"
    assert history[2]["status"] == "failed"
    assert history[2]["provider"] == "local"
    assert history[2]["result"] is None


def test_legacy_migration_backfills_original_without_inventing_provenance(database):
    paper_id = add(database, result())
    with database.connect() as connection:
        connection.execute("DROP TABLE classification_runs")
        for column in ("classification_provider", "classification_model", "classified_at"):
            connection.execute(f"ALTER TABLE papers DROP COLUMN {column}")
    database.initialize()
    database.initialize()
    paper = database.get_paper(paper_id)
    assert paper["ai_primary_category"] == "Authentication"
    assert paper["primary_category"] is None
    assert paper["classification_provider"] is None
    history = database.classification_history(paper_id)
    assert len(history) == 1
    assert history[0]["classified_at"] is None
    assert history[0]["result"]["primary_category"] == "Authentication"


def test_storage_validates_provider_before_inserting(database):
    with pytest.raises(ValidationError):
        add(database, result(), classification_provider="unexpected")
    assert database.dashboard_counts()["total"] == 0


def test_provider_failure_retry_and_explicit_reclassification(database, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "fixture.pdf").write_bytes(b"%PDF-1.4\nsynthetic")
    monkeypatch.setattr("src.scanner.parse_pdf", lambda *_: ParsedPDF("text", "title", {}, 1))
    monkeypatch.setattr("src.scanner.extract_metadata", lambda *_: ExtractedMetadata(
        title="A Study of Web Authentication", abstract="This research evaluates web authentication methods and security vulnerabilities. " * 3,
    ))

    class LocalMock:
        provider = "local"
        model = "mock-model"
        calls = 0

        def classify(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ClassificationError("Ollama classification failed (JSON/schema validation)")
            return result()

    classifier = LocalMock()
    kwargs = dict(inbox_dir=inbox, database=database, classifier=classifier, logger=logging.getLogger("test"))
    assert scan_inbox(**kwargs)[0].status == "Failed"
    paper_id = database.search_papers()[0]["id"]
    assert database.get_paper(paper_id)["classification_status"] == "failed"
    assert scan_inbox(**kwargs)[0].status == "Classified"
    assert database.get_paper(paper_id)["classification_status"] == "classified"
    assert scan_inbox(**kwargs)[0].status == "Skipped"
    assert classifier.calls == 2
    assert scan_inbox(**kwargs, reclassify=True)[0].status == "Classified"
    paper = database.get_paper(paper_id)
    assert paper["primary_category"] is None
    assert paper["tags"] == []
    assert paper["classification_provider"] == "local"
    assert database.dashboard_counts()["total"] == 1
    assert len(database.classification_history(paper_id)) == 3
