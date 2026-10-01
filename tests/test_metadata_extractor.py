from __future__ import annotations

from src.metadata_extractor import extract_metadata
from src.pdf_parser import ParsedPDF


def test_extracts_metadata_with_sources() -> None:
    parsed = ParsedPDF(
        text=(
            "A Study of Session Security\n"
            "Abstract\nThis paper presents a reproducible black-box evaluation of web session "
            "security across applications and measures session fixation defenses in practice.\n"
            "Keywords: session fixation; black-box testing\n"
            "1 Introduction\nBackground text"
        ),
        first_page_text="A Study of Session Security\nPublished 2025\nAbstract",
        metadata={"title": "A Study of Session Security", "author": "A. One; B. Two"},
        page_count=8,
    )
    result = extract_metadata(parsed, "paper.pdf")
    assert result.title == "A Study of Session Security"
    assert result.authors == ["A. One", "B. Two"]
    assert result.year == 2025
    assert "session fixation" in result.abstract.casefold()
    assert result.keywords == ["session fixation", "black-box testing"]
    assert result.metadata_sources["title"] == "PDF metadata"


def test_missing_metadata_uses_safe_filename_fallback() -> None:
    result = extract_metadata(
        ParsedPDF(text="", first_page_text="", metadata={}, page_count=0),
        "unknown_paper.pdf",
    )
    assert result.title == "unknown paper"
    assert result.abstract is None
    assert result.year is None
    assert result.authors == []
