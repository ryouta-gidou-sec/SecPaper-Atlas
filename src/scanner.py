"""Fault-isolated orchestration for scanning an inbox of source PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from pathlib import Path
import time
from typing import Protocol

from src.classifier import ClassificationError
from src.database import Database, DuplicatePaperError
from src.metadata_extractor import extract_metadata
from src.models import ClassificationResult, ExtractedMetadata
from src.pdf_parser import discover_pdfs, parse_pdf, sha256_file


class ClassifierProtocol(Protocol):
    def classify(
        self,
        *,
        title: str | None,
        abstract: str | None,
        keywords: list[str],
        introduction_excerpt: str | None = None,
    ) -> ClassificationResult: ...


@dataclass(frozen=True)
class ScanResult:
    filename: str
    status: str
    message: str
    paper_id: int | None = None
    processing_seconds: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def scan_inbox(
    *,
    inbox_dir: Path,
    database: Database,
    classifier: ClassifierProtocol | None,
    logger: logging.Logger,
) -> list[ScanResult]:
    """Process only unseen PDF hashes, isolating failures to a single paper."""

    results: list[ScanResult] = []
    for path in discover_pdfs(inbox_dir):
        started = time.perf_counter()
        try:
            file_hash = sha256_file(path)
            if database.paper_exists(file_hash):
                results.append(ScanResult(path.name, "Skipped", "Already registered"))
                continue

            parsed = parse_pdf(path, inbox_dir)
            metadata = extract_metadata(parsed, path.name)
            classification: ClassificationResult | None = None
            classification_error: str | None = None
            if classifier is None:
                classification_error = "OPENAI_API_KEY is not configured"
            else:
                try:
                    classification = classifier.classify(
                        title=metadata.title,
                        abstract=metadata.abstract,
                        keywords=metadata.keywords,
                        introduction_excerpt=metadata.introduction_excerpt,
                    )
                except ClassificationError as exc:
                    classification_error = str(exc)
                    logger.warning("Classification failed for hash=%s: %s", file_hash[:12], exc)

            elapsed = time.perf_counter() - started
            paper_id = database.add_paper(
                file_hash=file_hash,
                filename=path.name,
                filepath=str(path.resolve()),
                metadata=metadata,
                classification=classification,
                classification_error=classification_error,
                processing_seconds=elapsed,
            )
            if classification_error:
                results.append(
                    ScanResult(
                        path.name,
                        "Saved without AI classification",
                        classification_error,
                        paper_id,
                        elapsed,
                    )
                )
            else:
                results.append(
                    ScanResult(path.name, "Classified", "Success", paper_id, elapsed)
                )
            logger.info("Processed paper hash=%s status=%s", file_hash[:12], results[-1].status)
        except DuplicatePaperError:
            results.append(ScanResult(path.name, "Skipped", "Already registered"))
        except Exception as exc:
            # Log only the exception type; PDF contents and provider payloads stay private.
            logger.error("Paper processing failed file=%s error_type=%s", path.name, exc.__class__.__name__)
            results.append(
                ScanResult(
                    path.name,
                    "Failed",
                    f"Processing failed ({exc.__class__.__name__})",
                    processing_seconds=time.perf_counter() - started,
                )
            )
    return results
