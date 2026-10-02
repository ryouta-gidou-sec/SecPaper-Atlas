from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

from src.metadata_extractor import extract_metadata
from src.pdf_parser import discover_pdfs, has_pdf_signature, parse_pdf, sha256_file


def test_pdf_detection_checks_extension_and_signature(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    valid = inbox / "paper.PDF"
    valid.write_bytes(b"%PDF-1.7\nminimal")
    (inbox / "renamed.pdf").write_bytes(b"not a pdf")
    (inbox / "paper.txt").write_bytes(b"%PDF-1.7\nminimal")

    assert has_pdf_signature(valid)
    assert discover_pdfs(inbox) == [valid.resolve()]


def test_sha256_file_streams_stable_digest(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    content = b"%PDF-1.4\n" + (b"research" * 2000)
    path.write_bytes(content)
    assert sha256_file(path, chunk_size=17) == hashlib.sha256(content).hexdigest()


def test_parse_real_pdf_read_only(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Session Security Research")
    document.set_metadata({"title": "Session Security Research", "author": "A. Researcher"})
    document.save(path)
    document.close()
    original_bytes = path.read_bytes()

    parsed = parse_pdf(path, inbox)

    assert parsed.page_count == 1
    assert "Session Security Research" in parsed.first_page_text
    assert parsed.metadata["title"] == "Session Security Research"
    assert path.read_bytes() == original_bytes


def test_introduction_fallback_does_not_inspect_page_thirteen(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "bounded.pdf"
    with fitz.open() as document:
        for _ in range(12):
            document.new_page().insert_text((72, 72), "Front matter without a section heading")
        page = document.new_page()
        page.insert_text((72, 72), "1 Introduction")
        page.insert_text(
            (72, 100), "A useful introduction about deployed authentication systems. " * 4
        )
        document.set_metadata({"title": "A Reliable Paper Title"})
        document.save(path)
    before_hash = sha256_file(path)

    parsed = parse_pdf(path, inbox)
    result = extract_metadata(parsed, path.name)

    assert parsed.page_count == 13
    assert "1 Introduction" not in parsed.text
    assert result.introduction_excerpt is None
    assert result.review_reasons
    assert sha256_file(path) == before_hash
