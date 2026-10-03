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
    """A front-matter text block with lightweight layout information."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    direction: tuple[float, float] = (1.0, 0.0)


@dataclass(frozen=True)
class PDFPageLayout:
    """Bounded front-matter layout; later body pages remain text-only."""

    text: str
    blocks: tuple[PDFTextBlock, ...]
    size: tuple[float, float]


@dataclass(frozen=True)
class ParsedPDF:
    """Locally extracted PDF content used by the metadata stage."""

    text: str
    first_page_text: str
    metadata: dict[str, str]
    page_count: int
    first_page_blocks: tuple[PDFTextBlock, ...] = ()
    first_page_size: tuple[float, float] | None = None
    page_layouts: tuple[PDFPageLayout, ...] = ()


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
            page_layouts: list[PDFPageLayout] = []
            for page_number in range(min(document.page_count, max_pages)):
                page = document.load_page(page_number)
                page_text.append(page.get_text("text"))
                if page_number < 2:
                    size = (float(page.rect.width), float(page.rect.height))
                    layout_blocks = _extract_text_blocks(page)
                    page_layouts.append(PDFPageLayout(page_text[-1], layout_blocks, size))
                    if page_number == 0:
                        first_page_size = size
                        first_page_blocks = layout_blocks
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
                page_layouts=tuple(page_layouts),
            )
    except PDFParseError:
        raise
    except Exception as exc:
        raise PDFParseError(f"Unable to parse PDF ({exc.__class__.__name__})") from exc


def _extract_text_blocks(page: Any) -> tuple[PDFTextBlock, ...]:
    """Keep text block geometry, orientation and maximum span font size."""

    extracted: list[PDFTextBlock] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        # Separate mixed orientations so a margin label cannot give horizontal
        # title text its font size or bounding box.
        groups: dict[tuple[float, float], list[dict[str, Any]]] = {}
        for line in block.get("lines", []):
            direction = tuple(float(v) for v in line.get("dir", (1.0, 0.0)))
            groups.setdefault(direction, []).append(line)
        for direction, group in groups.items():
            text = "\n".join(
                "".join(str(span.get("text", "")) for span in line.get("spans", []))
                for line in group
            ).strip()
            boxes = [line.get("bbox", block.get("bbox")) for line in group]
            boxes = [box for box in boxes if box and len(box) == 4]
            if not text or not boxes:
                continue
            extracted.append(
                PDFTextBlock(
                    text=text[:6000],
                    x0=float(min(box[0] for box in boxes)),
                    y0=float(min(box[1] for box in boxes)),
                    x1=float(max(box[2] for box in boxes)),
                    y1=float(max(box[3] for box in boxes)),
                    font_size=max(
                        (float(span.get("size", 0.0)) for line in group
                         for span in line.get("spans", [])), default=0.0,
                    ),
                    direction=direction,
                )
            )
    return tuple(extracted)
