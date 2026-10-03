"""Synthetic front matter only; no user PDFs or research metadata."""

from pathlib import Path

import pytest

from src.metadata_extractor import extract_metadata
from src.pdf_parser import PDFPageLayout, PDFTextBlock, PDFTextLine, ParsedPDF, parse_pdf


TITLE = "Controlled Experiments in Authentication Security"
ABSTRACT = "We study deployed authentication systems and measure their behavior using controlled experiments."


def block(text: str, y: float, *, x: float = 60, size: float = 12) -> PDFTextBlock:
    return PDFTextBlock(text, x, y, x + 480, y + 16, size)


def extract(rows=(), *, text="", metadata=None):
    blocks = (block(TITLE, 60, size=16), *rows, block("Abstract", 390))
    first_page = text or "\n".join(b.text for b in blocks) + "\n" + ABSTRACT
    return extract_metadata(ParsedPDF(first_page, first_page, metadata or {}, 1,
                                     blocks, (612, 792)), "synthetic.pdf")


@pytest.mark.parametrize(("row", "expected"), [
    ("Alice Example, Bob Researcher and Carol Tester", ["Alice Example", "Bob Researcher", "Carol Tester"]),
    ("Alice Example1, Bob J Tester2 and Carol van Dijk3", ["Alice Example", "Bob J Tester", "Carol van Dijk"]),
    ("Alice Example†, Bob Researcher‡", ["Alice Example", "Bob Researcher"]),
    ("Alice Example¹, Bob Researcher²", ["Alice Example", "Bob Researcher"]),
    ("Alice Example1(B), Bob Researcher2", ["Alice Example", "Bob Researcher"]),
    ("Alice Example1,a)\nBob Researcher2", ["Alice Example", "Bob Researcher"]),
    ("Alice Example\nExample University", ["Alice Example"]),
    ("Alice Example, Example University, USA", ["Alice Example"]),
    ("Alice Example alice@example.org", ["Alice Example"]),
    ("Alice Example\nalice@example.org", ["Alice Example"]),
    ("Alice\nExample, Bob Researcher", ["Alice Example", "Bob Researcher"]),
    ("Alice Example,\nBob Researcher,\nCarol van Dijk", ["Alice Example", "Bob Researcher", "Carol van Dijk"]),
    ("山田太郎†\n鈴木花子‡", ["山田太郎", "鈴木花子"]),
    ("´Elena Example, André Tester", ["Élena Example", "André Tester"]),
    ("Alice Example\nDepartment of Computing\nSan Francisco", ["Alice Example"]),
])
def test_author_rows(row, expected):
    result = extract((block(row, 110),))
    assert result.authors == expected
    assert result.metadata_sources["authors"] == "first page layout"


@pytest.mark.parametrize("noise", [
    "Example Research Institute", "Technical University of Examples", "Dept. of Informatics",
    "International Security Conference", "Information Security Group", "Japan Science and Technology Agency",
    "17 Example Street", "San Francisco, CA 94105", "Independent researcher",
    "Example University\nRoyal Holloway, Another University", "imec-Lab, KU Example",
])
def test_institutions_and_addresses_are_not_authors(noise):
    result = extract((block(noise, 110),))
    assert result.authors == []
    assert "authors" not in result.metadata_sources
    assert not result.review_reasons


def test_wrapped_inline_affiliations_retain_all_authors():
    row = "Alice Example, Example University, USA\nBob van Dijk, Other University, USA"
    assert extract((block(row, 110),)).authors == ["Alice Example", "Bob van Dijk"]


def test_more_distant_author_rows_are_bounded_by_abstract():
    result = extract((block("Alice Example", 110), block("Bob Researcher", 225),
                      block("Carol Tester", 410)))
    assert result.authors == ["Alice Example", "Bob Researcher"]


def test_body_authors_override_incomplete_or_conflicting_pdf_properties():
    for author in ("Alice Example", "Unrelated Person", "Example Research Institute"):
        result = extract((block("Alice Example, Bob Researcher", 110),), metadata={"author": author})
        assert result.authors == ["Alice Example", "Bob Researcher"]
        assert result.metadata_sources["authors"] == "first page layout"


def test_corroborated_pdf_authors_keep_existing_provenance():
    result = extract((block("Alice Example, Bob Researcher", 110),),
                     metadata={"author": "Alice Example; Bob Researcher"})
    assert result.authors == ["Alice Example", "Bob Researcher"]
    assert result.metadata_sources["authors"] == "PDF metadata"


def test_pdf_authors_fallback_and_organization_rejection():
    for author, expected in (("Alice Example; Bob Researcher", ["Alice Example", "Bob Researcher"]),
                             ("Example Research Institute", []), ("San Francisco, CA 94105", [])):
        result = extract_metadata(ParsedPDF("", "", {"title": TITLE, "author": author}, 1), "sample.pdf")
        assert result.authors == expected


def test_line_geometry_excludes_body_text_in_a_mixed_block():
    lines = (PDFTextLine("Alice Example", 60, 120, 200, 135, 12),
             PDFTextLine("Unrelated Body", 60, 410, 200, 425, 12))
    mixed = PDFTextBlock("Alice Example\nUnrelated Body", 60, 120, 200, 425, 12, lines=lines)
    assert extract((mixed,)).authors == ["Alice Example"]


def test_unlabeled_summary_is_not_an_author_region():
    prose = "Our controlled experiments show that users benefit from clear authentication interfaces. " * 3
    result = extract((block("Alice Example", 110), block(prose, 160), block("False Person", 180)))
    assert result.authors == ["Alice Example"]


def test_proceedings_cover_uses_matching_body_page_only_for_authors():
    cover = "This paper is included in the Proceedings of the\n31st USENIX Security Symposium."
    cover_blocks = (block(TITLE, 230, size=20), block(cover, 440))
    body_blocks = (block(TITLE, 60, size=16), block("Alice Example, Bob Researcher", 110),
                   block("Abstract", 200), block(ABSTRACT, 220))
    body_text = "\n".join(b.text for b in body_blocks)
    parsed = ParsedPDF(cover + "\n\n" + body_text, cover, {}, 2, cover_blocks, (612, 792),
                       (PDFPageLayout(cover, cover_blocks, (612, 792)),
                        PDFPageLayout(body_text, body_blocks, (612, 792))))
    result = extract_metadata(parsed, "arbitrary.pdf")
    assert result.authors == ["Alice Example", "Bob Researcher"]
    assert result.metadata_sources["authors"] == "second page layout"
    assert result.metadata_sources["title"] == "first page cover layout"
    assert result.abstract == ABSTRACT


@pytest.mark.parametrize(("text", "year", "source"), [
    ("Published 2024", 2024, "first page publication header"),
    ("Copyright 2023 Example Publisher", 2023, "first page copyright line"),
    ("©2022 Example Publisher", 2022, "first page copyright line"),
    ("Journal of Security\nVol. 7, No. 2, April 2024", 2024, "first page journal header"),
    ("Network and Distributed System Security (NDSS) Symposium 2024", 2024, "first page proceedings header"),
    ("Received: 2020; Accepted: 2021; Published: Apr 18, 2024", 2024, "first page publication header"),
    ("arXiv:2403.12345v1 [cs.CR] 18 Mar 2024", None, None),
    ("Accessed 2024\nRetrieved 2023\nDownloaded 2022", None, None),
    ("Published 2023\nPublished 2024", None, None),
    ("Copyright 2023\nCopyright 2024", None, None),
    ("August 10, 2024", None, None),
    ("An abridged version appears in Conference 2023", None, None),
    ("The previous study was published: 2024", None, None),
    ("The copyright framework introduced in 2024 is discussed.", None, None),
])
def test_publication_year_evidence(text, year, source):
    result = extract(text=text)
    assert result.year == year
    assert result.metadata_sources.get("year") == source


def test_separate_proceedings_date_and_priority_over_copyright():
    text = "This paper is included in the Proceedings of the\n31st USENIX Security Symposium.\nAugust 10–12, 2024\n©2023 Publisher"
    assert extract(text=text).year == 2024


@pytest.mark.parametrize(("metadata", "expected"), [
    ({"year": "2024"}, 2024), ({"publicationyear": "2024"}, 2024),
    ({"publicationdate": "2024-02-10"}, 2024),
    ({"publicationdate": "2023-02-10; 2024-02-10"}, None),
    ({"creationDate": "D:20240210010000Z", "modDate": "D:20250210010000Z"}, None),
    ({"publicationyear": "2024; DROP TABLE papers"}, None),
    ({"publicationdate": "2024-99-01"}, None),
    ({"publicationdate": "2024-02-30"}, None),
])
def test_explicit_publication_metadata_only(metadata, expected):
    result = extract(metadata=metadata)
    assert result.year == expected
    if expected:
        assert result.metadata_sources["year"] == "PDF metadata"


def test_year_priority_header_then_event_then_metadata_then_copyright():
    result = extract(text="Journal of Security Vol. 2 (2024)\n©2021 Publisher",
                     metadata={"publicationyear": "2023"})
    assert result.year == 2024
    assert extract(text="©2021 Publisher", metadata={"publicationyear": "2023"}).year == 2023


@pytest.mark.parametrize(("text", "venue"), [
    ("32nd USENIX Security Symposium.", "USENIX Security Symposium"),
    ("Nineteenth Symposium on Usable Privacy and Security.", "Symposium on Usable Privacy and Security"),
    ("NDSS ’24, 23-26 February 2024", "NDSS"),
    ("Proceedings of the Example Security Conference 2024", "Example Security Conference"),
    ("Proceedings of the Example Security Workshop 2024", "Example Security Workshop"),
    ("Proceedings of the\n11th USENIX Security\nSymposium", "USENIX Security Symposium"),
    ("Journal of Experimental Security\nVol. 2, April 2024", "Journal of Experimental Security"),
    ("A. Editor (Eds.): ESORICS 2024, LNCS 12345", "ESORICS"),
    ("Example University\nExample Company\nExample Research Institute", None),
    ("Copyright 2024 Example Publisher\nSan Francisco", None),
    ("Ordinary Page Header", None),
    ("Ordinary Page Header Vol. 2 (2024)", None),
    ("Published at Example University", None),
    ("Published in Example Publisher", None),
    ("Published at Example Conference 2024", "Example Conference 2024"),
    ("Paper published at ExampleConf ’24.", "ExampleConf ’24"),
    ("We evaluate USENIX Security Symposium 2024 papers.", None),
    ("The experiments use data from USENIX Security Symposium 2024.", None),
    ("This publication studies NDSS ’24 papers.", None),
    ("[2] Example Journal Vol. 2 (2024)", None),
    ("", None),
])
def test_publication_venues(text, venue):
    assert extract(text=text).venue == venue


def test_pdf_subject_requires_publication_evidence():
    assert extract(text="Example University", metadata={"subject": "Example University"}).venue is None


def test_proceedings_footer_provenance():
    result = extract((block("NDSS ’24, 23-26 February 2024", 700),))
    assert result.venue == "NDSS"
    assert result.metadata_sources["venue"] == "first page proceedings footer"
    assert result.metadata_sources["year"] == "first page proceedings footer"


def test_proceedings_cover_provenance():
    result = extract(text="This paper is included in the Proceedings of the\nUSENIX Security Symposium 2024")
    assert result.metadata_sources["venue"] == "first page proceedings cover"


def test_parser_retains_lines_and_explicit_publication_properties(tmp_path: Path):
    import pymupdf as fitz

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "synthetic.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((60, 80), TITLE, fontsize=16)
        page.insert_text((60, 115), "Alice Example", fontsize=12)
        doc.set_metadata({"creationDate": "D:20210101000000Z"})
        info = int(doc.xref_get_key(-1, "Info")[1].split()[0])
        doc.xref_set_key(info, "PublicationYear", "(2024)")
        doc.save(path)
    parsed = parse_pdf(path, inbox)
    assert parsed.first_page_blocks[0].lines[0].text == TITLE
    assert extract_metadata(parsed, path.name).year == 2024


def test_xmp_publisher_date_excludes_creation_date(tmp_path: Path):
    import pymupdf as fitz

    path = tmp_path / "synthetic.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.set_xml_metadata('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
                             'xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/" '
                             'xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
                             '<rdf:Description prism:publicationDate="2024-04-01" '
                             'xmp:CreateDate="2020-01-01" /></rdf:RDF>')
        doc.save(path)
    parsed = parse_pdf(path, tmp_path)
    assert parsed.metadata["publicationdate"] == "2024-04-01"
    assert extract_metadata(parsed, path.name).year == 2024
