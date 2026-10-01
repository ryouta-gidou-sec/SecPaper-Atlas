"""Read-only PDF discovery, validation, hashing, and text extraction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any


PDF_SIGNATURE = b"%PDF-"


class PDFParseError(RuntimeError):
    """Raised when a candidate cannot be safely parsed as a PDF."""


@dataclass(frozen=True)
class ParsedPDF:
    """Locally extracted PDF content used by the metadata stage."""

    text: str
    first_page_text: str
    metadata: dict[str, str]
    page_count: int


def is_within_directory(path: Path, directory: Path) -> bool:
    """Return whether a resolved path remains inside a trusted directory."""

    try:
        path.resolve(strict=True).relative_to(directory.resolve(strict=True))
    except (FileNotFoundError, ValueError, OSError):
        return False
    return True


def has_pdf_signature(path: Path) -> bool:
    """Verify a file using both its extension and PDF magic bytes."""

    if not path.is_file() or path.suffix.casefold() != ".pdf":
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    except OSError:
        return False


def discover_pdfs(inbox_dir: Path) -> list[Path]:
    """Discover valid PDF candidates without following paths outside the inbox."""

    if not inbox_dir.exists():
        return []
    candidates: list[Path] = []
    for path in inbox_dir.rglob("*"):
        if is_within_directory(path, inbox_dir) and has_pdf_signature(path):
            candidates.append(path.resolve())
    return sorted(candidates, key=lambda item: str(item).casefold())


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a streaming SHA-256 digest without changing the file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pdf(path: Path, inbox_dir: Path, max_pages: int = 12) -> ParsedPDF:
    """Extract bounded local text after path and format validation.

    The source PDF is opened read-only. No PDF content is written back to disk.
    """

    if not is_within_directory(path, inbox_dir):
        raise PDFParseError("PDF path is outside the configured inbox")
    if not has_pdf_signature(path):
        raise PDFParseError("File does not have a valid PDF signature")

    try:
        import fitz  # PyMuPDF is imported lazily for clearer setup errors.

        with fitz.open(path) as document:
            if document.needs_pass:
                raise PDFParseError("Encrypted PDF requires a password")
            page_text: list[str] = []
            for page_number in range(min(document.page_count, max_pages)):
                page_text.append(document.load_page(page_number).get_text("text"))
            raw_metadata: dict[str, Any] = document.metadata or {}
            metadata = {
                str(key): str(value).strip()
                for key, value in raw_metadata.items()
                if value is not None and str(value).strip()
            }
            return ParsedPDF(
                text="\n\n".join(page_text),
                first_page_text=page_text[0] if page_text else "",
                metadata=metadata,
                page_count=document.page_count,
            )
    except PDFParseError:
        raise
    except Exception as exc:
        raise PDFParseError(f"Unable to parse PDF ({exc.__class__.__name__})") from exc
