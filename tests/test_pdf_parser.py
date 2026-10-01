from __future__ import annotations

import hashlib
from pathlib import Path

import fitz

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
