"""Fault-isolated orchestration for scanning an inbox of source PDFs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from pathlib import Path
import time

from src.classifier import ClassificationError, ClassifierProvider
from src.database import Database, DuplicatePaperError
from src.metadata_extractor import classification_input_issues, extract_metadata
from src.models import ClassificationResult, ClassificationStatus, ExtractedMetadata
from src.pdf_parser import discover_pdfs, parse_pdf, sha256_file


ClassifierProtocol = ClassifierProvider


@dataclass(frozen=True)
class ScanResult:
    """Per-paper outcome; elapsed time stops before persistence, result logging and UI work."""

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
    reclassify: bool = False,
) -> list[ScanResult]:
    """Scan papers, measuring each non-skipped attempt through provider validation.

    Duration includes hashing, duplicate lookup, parsing, extraction, input gating,
    and any provider preflight/generation/validation retries. DB writes, logging
    after measurement, and UI rendering are excluded. This is not AI-only time.
    """

    results: list[ScanResult] = []
    for path in discover_pdfs(inbox_dir):
        started = time.perf_counter()
        try:
            file_hash = sha256_file(path)
            existing = database.get_paper_by_hash(file_hash)
            retrying = existing is not None and (reclassify or existing["classification_status"] in {
                ClassificationStatus.PENDING.value,
                ClassificationStatus.FAILED.value,
                ClassificationStatus.NEEDS_REVIEW.value,
            })
            if existing is not None and not retrying:
                results.append(ScanResult(path.name, "Skipped", "Already registered"))
                continue

            parsed = parse_pdf(path, inbox_dir)
            metadata = extract_metadata(parsed, path.name)
            input_issues = list(metadata.review_reasons)
            input_issues.extend(
                issue
                for issue in classification_input_issues(
                    title=metadata.title,
                    abstract=metadata.abstract,
                    introduction_excerpt=metadata.introduction_excerpt,
                )
                if issue not in input_issues
            )
            classification: ClassificationResult | None = None
            classification_error: str | None = None
            if input_issues:
                classification_status = ClassificationStatus.NEEDS_REVIEW
                classification_error = "Classification held for metadata review"
            elif classifier is None:
                classification_status = ClassificationStatus.PENDING
                classification_error = "Classifier is not configured"
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
                    classification_status = ClassificationStatus.FAILED
                    logger.warning("Classification failed for hash=%s: %s", file_hash[:12], exc)
                else:
                    classification_status = ClassificationStatus.CLASSIFIED

            # Keep the same measurement boundary for inserts and existing records.
            elapsed = time.perf_counter() - started
            if existing is not None:
                paper_id = int(existing["id"])
                database.update_metadata(
                    paper_id,
                    metadata,
                    classification_status=(
                        ClassificationStatus.PENDING
                        if classification
                        else classification_status
                    ),
                    classification_error=(
                        None if classification else classification_error
                    ),
                )
                database.update_classification(
                    paper_id,
                    classification,
                    classification_status=classification_status,
                    classification_error=classification_error,
                    classification_provider=getattr(classifier, "provider", None),
                    classification_model=getattr(classifier, "model", None),
                    processing_seconds=elapsed,
                )
            else:
                paper_id = database.add_paper(
                    file_hash=file_hash,
                    filename=path.name,
                    filepath=str(path.resolve()),
                    metadata=metadata,
                    classification=classification,
                    classification_error=classification_error,
                    classification_status=classification_status,
                    processing_seconds=elapsed,
                    classification_provider=getattr(classifier, "provider", None),
                    classification_model=getattr(classifier, "model", None),
                )
            if classification_error:
                result_status = {
                    ClassificationStatus.NEEDS_REVIEW: "Needs review",
                    ClassificationStatus.FAILED: "Failed",
                    ClassificationStatus.PENDING: "Pending",
                }[classification_status]
                results.append(
                    ScanResult(
                        path.name,
                        result_status,
                        classification_error,
                        paper_id,
                        elapsed,
                    )
                )
            else:
                results.append(
                    ScanResult(
                        path.name,
                        "Classified",
                        "Classification retry succeeded" if retrying else "Success",
                        paper_id,
                        elapsed,
                    )
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
