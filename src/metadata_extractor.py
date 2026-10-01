"""Conservative metadata extraction from PDF properties and local text."""

from __future__ import annotations

from pathlib import Path
import re

from src.models import ExtractedMetadata
from src.pdf_parser import ParsedPDF


YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
ABSTRACT_PATTERN = re.compile(
    r"(?is)(?:^|\n)\s*abstract\s*[:.\u2014-]?\s*(.{80,6000}?)"
    r"(?=\n\s*(?:keywords?|index\s+terms|(?:1[.\s]+)?introduction)\b)"
)
ABSTRACT_FALLBACK_PATTERN = re.compile(
    r"(?is)(?:^|\n)\s*abstract\s*[:.\u2014-]?\s*(.{80,2500})"
)
KEYWORDS_PATTERN = re.compile(
    r"(?im)^\s*(?:keywords?|index\s+terms)\s*[:.\u2014-]?\s*(.{3,800})$"
)
INTRODUCTION_PATTERN = re.compile(
    r"(?is)(?:^|\n)\s*(?:1[.\s]+)?introduction\s*\n?(.{100,2500})"
)


def extract_metadata(parsed: ParsedPDF, filename: str) -> ExtractedMetadata:
    """Extract only defensible metadata and record the source of each value."""

    sources: dict[str, str] = {}
    title = _metadata_value(parsed.metadata, "title")
    if title and not _looks_generic(title):
        sources["title"] = "PDF metadata"
    else:
        title = _title_from_first_page(parsed.first_page_text)
        if title:
            sources["title"] = "first page"
        else:
            fallback = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
            title = fallback or None
            if title:
                sources["title"] = "filename fallback"

    authors = _split_people(_metadata_value(parsed.metadata, "author"))
    if authors:
        sources["authors"] = "PDF metadata"

    abstract = _extract_abstract(parsed.text)
    if abstract:
        sources["abstract"] = "extracted text"

    keywords = _extract_keywords(parsed.text)
    if not keywords:
        keywords = _split_keywords(_metadata_value(parsed.metadata, "keywords"))
        if keywords:
            sources["keywords"] = "PDF metadata"
    else:
        sources["keywords"] = "extracted text"

    year = _extract_year(parsed.metadata, parsed.first_page_text)
    if year:
        sources["year"] = year[1]

    venue = _metadata_value(parsed.metadata, "subject")
    if venue and _looks_generic(venue):
        venue = None
    if venue:
        sources["venue"] = "PDF metadata subject"

    introduction = None if abstract else _extract_introduction(parsed.text)
    if introduction:
        sources["introduction_excerpt"] = "extracted text"

    return ExtractedMetadata(
        title=title,
        authors=authors,
        year=year[0] if year else None,
        venue=venue,
        abstract=abstract,
        keywords=keywords,
        introduction_excerpt=introduction,
        metadata_sources=sources,
    )


def _metadata_value(metadata: dict[str, str], key: str) -> str | None:
    value = metadata.get(key) or metadata.get(key.title())
    return " ".join(value.split()) if value else None


def _looks_generic(value: str) -> bool:
    lowered = value.casefold().strip()
    generic = {"untitled", "unknown", "document", "microsoft word", "none"}
    return lowered in generic or lowered.startswith("microsoft word -")


def _title_from_first_page(text: str) -> str | None:
    candidates: list[str] = []
    for line in text.splitlines()[:30]:
        cleaned = " ".join(line.split()).strip(" -")
        lowered = cleaned.casefold()
        if (
            12 <= len(cleaned) <= 300
            and "abstract" not in lowered
            and not lowered.startswith(("http", "doi", "arxiv", "proceedings"))
            and not YEAR_PATTERN.fullmatch(cleaned)
        ):
            candidates.append(cleaned)
        if "abstract" in lowered:
            break
    return max(candidates[:8], key=len, default=None)


def _split_people(value: str | None) -> list[str]:
    if not value:
        return []
    separator = ";" if ";" in value else " and " if " and " in value else None
    if separator:
        return [item.strip() for item in value.split(separator) if item.strip()]
    return [value.strip()]


def _split_keywords(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip(" .") for item in re.split(r"[;,]", value) if item.strip(" .")]


def _extract_abstract(text: str) -> str | None:
    match = ABSTRACT_PATTERN.search(text) or ABSTRACT_FALLBACK_PATTERN.search(text)
    if not match:
        return None
    return " ".join(match.group(1).split())[:6000] or None


def _extract_keywords(text: str) -> list[str]:
    match = KEYWORDS_PATTERN.search(text[:30_000])
    return _split_keywords(match.group(1)) if match else []


def _extract_introduction(text: str) -> str | None:
    match = INTRODUCTION_PATTERN.search(text)
    if not match:
        return None
    return " ".join(match.group(1).split())[:2500] or None


def _extract_year(metadata: dict[str, str], first_page_text: str) -> tuple[int, str] | None:
    for key in ("creationDate", "modDate"):
        value = _metadata_value(metadata, key)
        match = YEAR_PATTERN.search(value or "")
        if match:
            return int(match.group()), "PDF metadata"
    years = [int(item) for item in YEAR_PATTERN.findall(first_page_text[:10_000])]
    plausible = [year for year in years if 1950 <= year <= 2100]
    return (plausible[0], "first page") if plausible else None
