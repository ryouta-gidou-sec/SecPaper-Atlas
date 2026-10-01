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
class PDFTextBlock:
    """A first-page text block with lightweight layout information."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float


@dataclass(frozen=True)
class ParsedPDF:
    """Locally extracted PDF content used by the metadata stage."""

    text: str
    first_page_text: str
    metadata: dict[str, str]
    page_count: int
    first_page_blocks: tuple[PDFTextBlock, ...] = ()
    first_page_size: tuple[float, float] | None = None


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
        import pymupdf as fitz  # Imported lazily for clearer setup errors.

        with fitz.open(path) as document:
            if document.needs_pass:
                raise PDFParseError("Encrypted PDF requires a password")
            page_text: list[str] = []
            first_page_blocks: tuple[PDFTextBlock, ...] = ()
            first_page_size: tuple[float, float] | None = None
            for page_number in range(min(document.page_count, max_pages)):
                page = document.load_page(page_number)
                page_text.append(page.get_text("text"))
                if page_number == 0:
                    first_page_size = (float(page.rect.width), float(page.rect.height))
                    first_page_blocks = _extract_text_blocks(page)
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
                first_page_blocks=first_page_blocks,
                first_page_size=first_page_size,
            )
    except PDFParseError:
        raise
    except Exception as exc:
        raise PDFParseError(f"Unable to parse PDF ({exc.__class__.__name__})") from exc


def _extract_text_blocks(page: Any) -> tuple[PDFTextBlock, ...]:
    """Keep text block geometry and dominant font size for front-matter heuristics."""

    extracted: list[PDFTextBlock] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        lines: list[str] = []
        font_sizes: list[float] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            lines.append("".join(str(span.get("text", "")) for span in spans))
            font_sizes.extend(float(span.get("size", 0.0)) for span in spans)
        text = "\n".join(lines).strip()
        bbox = block.get("bbox")
        if not text or not bbox or len(bbox) != 4:
            continue
        extracted.append(
            PDFTextBlock(
                text=text[:5000],
                x0=float(bbox[0]),
                y0=float(bbox[1]),
                x1=float(bbox[2]),
                y1=float(bbox[3]),
                font_size=max(font_sizes, default=0.0),
            )
        )
    return tuple(extracted)
