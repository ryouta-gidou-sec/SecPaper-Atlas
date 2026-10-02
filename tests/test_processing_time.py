"""Deterministic regression checks for the latest scanner attempt's duration."""

import logging
from types import SimpleNamespace

import pytest

from src.classifier import ClassificationError
from src.models import ClassificationResult, ExtractedMetadata
from src.pdf_parser import ParsedPDF, sha256_file
from src.scanner import scan_inbox


@pytest.fixture
def timed_scan(tmp_path, database, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic timing regression")
    clock = SimpleNamespace(seconds=100.0)
    metadata = ExtractedMetadata(
        title="Automated Detection of Session Security Vulnerabilities",
        authors=["Synthetic Author One", "Synthetic Author Two"],
        year=2024,
        venue="Synthetic Security Conference",
        abstract="This study evaluates automated session vulnerability detection using attack simulation. " * 3,
        keywords=["session security", "attack simulation"],
        metadata_sources={"title": "page_text", "abstract": "page_text"},
    )

    def parse(*_):
        clock.seconds += 2.0
        return ParsedPDF("synthetic text", metadata.title, {}, 1)

    def extract(*_):
        clock.seconds += 3.0
        return metadata

    class TimedClassifier:
        provider = "local"
        model = "synthetic-model"
        seconds = 7.0
        fail = False
        calls = 0

        def classify(self, **_):
            self.calls += 1
            clock.seconds += self.seconds
            if self.fail:
                raise ClassificationError("Synthetic classification failure")
            return ClassificationResult(
                primary_category="Session Management",
                tags=["Session Fixation"],
                research_methods=["Attack Simulation"],
                target_vulnerabilities=["Session Fixation"],
                relevance="A",
                relevance_reason="Synthetic session detection study.",
                relevance_confidence=0.9,
            )

    monkeypatch.setattr("src.scanner.time", SimpleNamespace(perf_counter=lambda: clock.seconds))
    monkeypatch.setattr("src.scanner.parse_pdf", parse)
    monkeypatch.setattr("src.scanner.extract_metadata", extract)
    classifier = TimedClassifier()
    return SimpleNamespace(
        path=path, metadata=metadata, classifier=classifier,
        kwargs=dict(inbox_dir=inbox, database=database, classifier=classifier,
                    logger=logging.getLogger("test.processing_time")),
    )


def test_new_classification_saves_extraction_plus_classification_time(database, timed_scan):
    result = scan_inbox(**timed_scan.kwargs)[0]
    paper = database.get_paper(result.paper_id)
    assert result.status == "Classified"
    assert result.processing_seconds == 12.0  # parsing 2 + extraction 3 + classification 7
    assert paper["processing_seconds"] == result.processing_seconds
    assert database.classification_history(paper["id"])[0]["result"]["primary_category"] == "Session Management"


@pytest.mark.parametrize("reviewed", [False, True])
def test_reclassification_updates_time_preserving_metadata_history_and_human_values(
    database, timed_scan, reviewed,
):
    first = scan_inbox(**timed_scan.kwargs)[0]
    paper_id = first.paper_id
    if reviewed:
        database.update_review(
            paper_id, primary_category="Authorization", tags=["Human tag"],
            relevance="B", status="Read", research_methods=["Survey"],
            target_vulnerabilities=["Human vulnerability"], relevance_reason="Human review.",
        )
    before = database.get_paper(paper_id)
    history_before = database.classification_history(paper_id)
    other_id = database.add_paper(
        file_hash="b" * 64, filename="other.pdf", filepath="other.pdf",
        metadata=ExtractedMetadata(title="Another Synthetic Paper"),
        classification=None, processing_seconds=8.0,
    )
    other_before = database.get_paper(other_id)
    timed_scan.classifier.seconds = 21.0
    second = scan_inbox(**timed_scan.kwargs, reclassify=True)[0]
    after = database.get_paper(paper_id)
    assert second.status == "Classified"
    assert after["processing_seconds"] == second.processing_seconds == 26.0
    assert after["processing_seconds"] != before["processing_seconds"]
    for key in (
        "id", "file_hash", "filename", "filepath", "title", "authors", "year", "venue",
        "abstract", "introduction_excerpt", "keywords", "metadata_sources", "metadata_review_reasons",
        "created_at", "primary_category", "tags", "research_methods", "target_vulnerabilities",
        "relevance", "relevance_reason", "relevance_confidence", "manually_reviewed", "status",
    ):
        assert after[key] == before[key], key
    assert database.get_paper(other_id) == other_before
    history_after = database.classification_history(paper_id)
    assert history_after[:-1] == history_before
    assert history_after[-1]["result"] == history_before[-1]["result"]
    assert history_after[-1]["provider"] == after["classification_provider"] == "local"
    assert history_after[-1]["model"] == after["classification_model"] == "synthetic-model"
    assert history_after[-1]["classified_at"] == after["classified_at"]
    assert database.dashboard_counts()["total"] == 2


@pytest.mark.parametrize("status", ["pending", "failed", "needs_review"])
def test_incomplete_record_retry_updates_time(database, timed_scan, status):
    paper_id = database.add_paper(
        file_hash=sha256_file(timed_scan.path), filename=timed_scan.path.name,
        filepath=str(timed_scan.path), metadata=timed_scan.metadata,
        classification=None, classification_status=status, processing_seconds=0.084,
    )
    result = scan_inbox(**timed_scan.kwargs)[0]
    assert result.status == "Classified"
    assert database.get_paper(paper_id)["processing_seconds"] == result.processing_seconds == 12.0


def test_failed_retry_saves_latest_attempt_time_and_retains_success_history(database, timed_scan):
    first = scan_inbox(**timed_scan.kwargs)[0]
    before = database.get_paper(first.paper_id)
    history_before = database.classification_history(first.paper_id)
    timed_scan.classifier.fail = True
    timed_scan.classifier.seconds = 4.0
    result = scan_inbox(**timed_scan.kwargs, reclassify=True)[0]
    after = database.get_paper(first.paper_id)
    assert result.status == "Failed"
    assert after["processing_seconds"] == result.processing_seconds == 9.0
    assert after["classification_status"] == "failed"
    for key in ("ai_primary_category", "ai_tags", "classification_provider", "classification_model", "classified_at"):
        assert after[key] == before[key]
    history_after = database.classification_history(first.paper_id)
    assert history_after[:-1] == history_before
    assert history_after[-1]["status"] == "failed"
    assert history_after[-1]["result"] is None


def test_skipped_classified_paper_keeps_previous_time_and_history(database, timed_scan):
    first = scan_inbox(**timed_scan.kwargs)[0]
    before = database.get_paper(first.paper_id)
    history_before = database.classification_history(first.paper_id)
    assert scan_inbox(**timed_scan.kwargs)[0].status == "Skipped"
    assert database.get_paper(first.paper_id) == before
    assert database.classification_history(first.paper_id) == history_before
    assert timed_scan.classifier.calls == 1


def test_direct_classification_update_preserves_omitted_time_and_accepts_zero(database, timed_scan):
    first = scan_inbox(**timed_scan.kwargs)[0]
    classification = ClassificationResult.model_validate(
        database.classification_history(first.paper_id)[-1]["result"]
    )
    kwargs = dict(classification_status="classified", classification_provider="local",
                  classification_model="synthetic-model")
    database.update_classification(first.paper_id, classification, **kwargs)
    assert database.get_paper(first.paper_id)["processing_seconds"] == 12.0
    database.update_classification(first.paper_id, classification, processing_seconds=0.0, **kwargs)
    assert database.get_paper(first.paper_id)["processing_seconds"] == 0.0
    assert len(database.classification_history(first.paper_id)) == 3


@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf"), True, "1.5"])
def test_storage_rejects_invalid_duration_without_changing_papers_or_history(
    database, timed_scan, operation, invalid,
):
    first = scan_inbox(**timed_scan.kwargs)[0]
    before = database.get_paper(first.paper_id)
    history_before = database.classification_history(first.paper_id)
    classification = ClassificationResult.model_validate(history_before[-1]["result"])
    with pytest.raises(ValueError, match="processing_seconds"):
        if operation == "insert":
            database.add_paper(
                file_hash="c" * 64, filename="invalid-time.pdf", filepath="invalid-time.pdf",
                metadata=timed_scan.metadata, classification=classification,
                processing_seconds=invalid,
            )
        else:
            database.update_classification(
                first.paper_id, classification, classification_status="classified",
                processing_seconds=invalid,
            )
    assert database.get_paper(first.paper_id) == before
    assert database.classification_history(first.paper_id) == history_before
    assert database.dashboard_counts()["total"] == 1


def test_duration_and_classification_history_rollback_together(database, timed_scan, monkeypatch):
    first = scan_inbox(**timed_scan.kwargs)[0]
    before = database.get_paper(first.paper_id)
    history_before = database.classification_history(first.paper_id)
    classification = ClassificationResult.model_validate(history_before[-1]["result"])

    def fail_label_write(*_):
        raise RuntimeError("Synthetic label write failure")

    monkeypatch.setattr(database, "_replace_labels", fail_label_write)
    with pytest.raises(RuntimeError, match="Synthetic label write failure"):
        database.update_classification(
            first.paper_id, classification, classification_status="classified",
            classification_provider="local", classification_model="another-model",
            processing_seconds=99.0,
        )
    assert database.get_paper(first.paper_id) == before
    assert database.classification_history(first.paper_id) == history_before
