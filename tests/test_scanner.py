from __future__ import annotations

import logging
from pathlib import Path

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
        lambda *_: ExtractedMetadata(title="Paper", abstract="Abstract"),
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
        return ExtractedMetadata(title="Good Paper")

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
