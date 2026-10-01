from __future__ import annotations

import logging
from pathlib import Path

from src.classifier import ClassificationError
from src.database import Database
from src.models import ClassificationResult, ExtractedMetadata
from src.pdf_parser import ParsedPDF
from src.scanner import scan_inbox


class FakeClassifier:
    def classify(self, **_: object) -> ClassificationResult:
        return ClassificationResult(
            primary_category="Authentication",
            tags=["Authentication"],
            research_methods=["Empirical Study"],
            target_vulnerabilities=["Authentication Bypass"],
            relevance="B",
            relevance_reason="Authentication research is relevant.",
            relevance_confidence=0.85,
        )


def test_scan_registers_new_pdf_once(
    tmp_path: Path, database: Database, monkeypatch: object
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "paper.pdf").write_bytes(b"%PDF-1.4\ntest")
    parsed = ParsedPDF("text", "title", {}, 1)
    monkeypatch.setattr("src.scanner.parse_pdf", lambda *_: parsed)
    monkeypatch.setattr(
        "src.scanner.extract_metadata",
        lambda *_: ExtractedMetadata(
            title="A Valid Paper About Session Security",
            abstract=(
                "This abstract explains the study and reports a reproducible evaluation "
                "of session security. "
            )
            * 2,
        ),
    )

    first = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=FakeClassifier(),
        logger=logging.getLogger("test"),
    )
    second = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=FakeClassifier(),
        logger=logging.getLogger("test"),
    )
    assert first[0].status == "Classified"
    assert second[0].status == "Skipped"
    assert database.dashboard_counts()["total"] == 1


def test_metadata_failure_does_not_stop_remaining_papers(
    tmp_path: Path, database: Database, monkeypatch: object
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "bad.pdf").write_bytes(b"%PDF-1.4\nbad")
    (inbox / "good.pdf").write_bytes(b"%PDF-1.4\ngood")

    def parse(path: Path, _: Path) -> ParsedPDF:
        return ParsedPDF(path.name, path.name, {}, 1)

    def extract(parsed: ParsedPDF, _: str) -> ExtractedMetadata:
        if parsed.text == "bad.pdf":
            raise ValueError("missing metadata")
        return ExtractedMetadata(
            title="A Good Paper About Authentication",
            abstract=(
                "This abstract summarizes the approach and its evaluation of authentication "
                "security. "
            )
            * 2,
        )

    monkeypatch.setattr("src.scanner.parse_pdf", parse)
    monkeypatch.setattr("src.scanner.extract_metadata", extract)
    results = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=FakeClassifier(),
        logger=logging.getLogger("test"),
    )
    assert [result.status for result in results] == ["Failed", "Classified"]
    assert database.dashboard_counts()["total"] == 1


def test_classification_error_is_reported_as_failed_not_pending(
    tmp_path: Path, database: Database, monkeypatch: object
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "paper.pdf").write_bytes(b"%PDF-1.4\ntest")
    metadata = ExtractedMetadata(
        title="A Valid Paper About Session Security",
        abstract=(
            "This abstract explains the study and reports a reproducible evaluation "
            "of session security. "
        )
        * 2,
    )
    monkeypatch.setattr(
        "src.scanner.parse_pdf", lambda *_: ParsedPDF("text", "title", {}, 1)
    )
    monkeypatch.setattr("src.scanner.extract_metadata", lambda *_: metadata)

    class FailingClassifier:
        def classify(self, **_: object) -> ClassificationResult:
            raise ClassificationError("OpenAI classification failed (RateLimitError)")

    result = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=FailingClassifier(),
        logger=logging.getLogger("test"),
    )
    stored = database.search_papers()[0]
    assert result[0].status == "Failed"
    assert stored["classification_status"] == "failed"
    assert stored["classification_error"] == "OpenAI classification failed (RateLimitError)"


def test_pending_record_can_be_retried_without_overwriting_human_values(
    tmp_path: Path, database: Database, monkeypatch: object
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "paper.pdf").write_bytes(b"%PDF-1.4\ntest")
    parsed = ParsedPDF("text", "title", {}, 1)
    metadata = ExtractedMetadata(
        title="A Valid Paper About Session Security",
        abstract=(
            "This abstract explains the study and reports a reproducible evaluation "
            "of session security. "
        )
        * 2,
    )
    monkeypatch.setattr("src.scanner.parse_pdf", lambda *_: parsed)
    monkeypatch.setattr("src.scanner.extract_metadata", lambda *_: metadata)

    first = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=None,
        logger=logging.getLogger("test"),
    )
    stored = database.search_papers()[0]
    assert first[0].status == "Pending"
    assert stored["classification_status"] == "pending"
    paper_id = stored["id"]
    database.update_review(
        paper_id,
        primary_category="Vulnerability Assessment",
        tags=["Human selected tag"],
        relevance="C",
        status="Read",
        research_methods=["Survey"],
        target_vulnerabilities=["Human selected vulnerability"],
    )

    second = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=FakeClassifier(),
        logger=logging.getLogger("test"),
    )
    reviewed = database.get_paper(paper_id)
    assert second[0].status == "Classified"
    assert database.dashboard_counts()["total"] == 1
    assert reviewed["classification_status"] == "classified"
    assert reviewed["ai_primary_category"] == "Authentication"
    assert reviewed["primary_category"] == "Vulnerability Assessment"
    assert reviewed["tags"] == ["Human selected tag"]
    assert reviewed["ai_tags"] == ["Authentication"]


def test_low_quality_metadata_is_saved_for_review_without_classifier_call(
    tmp_path: Path, database: Database, monkeypatch: object
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "paper.pdf").write_bytes(b"%PDF-1.4\ntest")
    parsed = ParsedPDF("text", "title", {}, 1)
    metadata = ExtractedMetadata(
        title="A Valid Paper About Session Security",
        abstract=None,
        review_reasons=["Neither an abstract nor an introduction excerpt was found."],
    )

    class CountingClassifier(FakeClassifier):
        calls = 0

        def classify(self, **kwargs: object) -> ClassificationResult:
            self.calls += 1
            return super().classify(**kwargs)

    monkeypatch.setattr("src.scanner.parse_pdf", lambda *_: parsed)
    monkeypatch.setattr("src.scanner.extract_metadata", lambda *_: metadata)
    classifier = CountingClassifier()
    result = scan_inbox(
        inbox_dir=inbox,
        database=database,
        classifier=classifier,
        logger=logging.getLogger("test"),
    )
    stored = database.search_papers()[0]
    assert result[0].status == "Needs review"
    assert classifier.calls == 0
    assert stored["classification_status"] == "needs_review"
