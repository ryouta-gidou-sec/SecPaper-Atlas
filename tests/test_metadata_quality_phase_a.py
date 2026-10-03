"""Synthetic front-matter fixtures; no personal PDFs or audit data."""
from pathlib import Path

import pymupdf as fitz
import pytest

from src.metadata_extractor import classification_input_issues, extract_metadata
from src.pdf_parser import PDFPageLayout, PDFTextBlock, ParsedPDF, parse_pdf, sha256_file


TITLE = "Analyzing Access Policies in Distributed Applications"
PARAGRAPHS = (
    "We study deployed access policies and identify their limitations through controlled "
    "experiments across multiple distributed applications.",
    "Our method models delegated authorization and verifies security properties under "
    "realistic adversarial conditions using a formal analysis.",
    "The evaluation reveals previously unknown implementation flaws and demonstrates "
    "that our mitigations preserve both security and performance.",
)


def b(text, y, font=10, x=50, width=250, height=18, direction=(1.0, 0.0)):
    return PDFTextBlock(text, x, y, x + width, y + height, font, direction)


def extract(text, blocks=(), metadata=None, page_layouts=()):
    return extract_metadata(ParsedPDF(
        text, text, metadata if metadata is not None else {"title": TITLE}, 2,
        blocks, (600, 800), page_layouts,
    ), "synthetic.pdf")


def test_rotated_arxiv_label_loses_to_horizontal_title(tmp_path: Path):
    path = tmp_path / "synthetic.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text((30, 350), "arXiv:2401.12345v1 [cs.CR] 1 Jan 2024", fontsize=20, rotate=90)
        page.insert_text((80, 65), TITLE, fontsize=14.35)
        page.insert_text((80, 150), "Abstract", fontsize=10)
        page.insert_textbox(fitz.Rect(80, 170, 520, 300), PARAGRAPHS[0], fontsize=10)
        pdf.save(path)
    original_hash = sha256_file(path)
    parsed = parse_pdf(path, tmp_path)
    rotated = next(block for block in parsed.first_page_blocks if "arXiv" in block.text)
    assert rotated.direction == (0.0, -1.0)
    assert extract_metadata(parsed, path.name).title == TITLE
    assert sha256_file(path) == original_hash


@pytest.mark.parametrize("false_title", [
    "arXiv:2401.12345v2 [cs.CR] 2 Jan 2024",
    "arXiv:hep-th/9901001v1 1 Jan 1999", "main-usenix0", "submission_final", "main.tex",
    "Proceedings of the 17th Security Symposium",
])
def test_invalid_properties_and_quality_gate(false_title):
    result = extract("", (b(TITLE, 60, 14.35, width=500),), {"title": false_title})
    assert result.title == TITLE
    assert classification_input_issues(title=false_title, abstract=PARAGRAPHS[0],
                                       introduction_excerpt=None)


def test_valid_metadata_title_used_after_invalid_layout():
    result = extract("", (b("arXiv:2401.12345v1 [cs.CR] 1 Jan 2024", 60, 20),),
                     {"title": TITLE})
    assert result.title == TITLE
    assert result.metadata_sources["title"] == "PDF metadata"


def test_rotation_is_filtered_even_without_an_arxiv_identifier():
    result = extract("", (b("Vertical Publisher Label", 60, 20, width=500, direction=(0, -1)),
                          b(TITLE, 80, 14.35, width=500)), {})
    assert result.title == TITLE


def test_proceedings_header_is_filtered_on_an_article_page():
    result = extract("", (b("Proceedings of the 17th Security Symposium", 40, 24, width=500),
                          b(TITLE, 100, 16, width=500)), {})
    assert result.title == TITLE


def test_internal_metadata_name_does_not_override_a_valid_cover_title():
    blocks = (b(TITLE, 240, 21, width=500),
              b("This paper is included in the Proceedings of the", 430, 18, width=500),
              b("33rd USENIX Security Symposium", 455, 18, width=500))
    result = extract("\n".join(block.text for block in blocks), blocks, {"title": "main-conf0"})
    assert result.title == TITLE
    assert result.metadata_sources["title"] == "first page cover layout"


def test_proceedings_only_cover_recovers_body_title_and_abstract():
    cover = "Proceedings of the 17th Security Symposium"
    body = f"{TITLE}\nAbstract\n{PARAGRAPHS[0]}\n1. Motivation\nUNRELATED BODY"
    body_blocks = (b(TITLE, 60, 16, width=500), b("Abstract", 140),
                   b(PARAGRAPHS[0], 160), b("1. Motivation", 210))
    result = extract(cover, (b(cover, 100, 24),), {}, (
        PDFPageLayout(cover, (b(cover, 100, 24),), (600, 800)),
        PDFPageLayout(body, body_blocks, (600, 800)),
    ))
    assert result.title == TITLE
    assert result.abstract == PARAGRAPHS[0]
    assert result.metadata_sources["title"] == "second page layout"
    assert result.metadata_sources["abstract"] == "second page layout"


def test_proceedings_cover_does_not_promote_a_second_page_section_title():
    cover = "Proceedings of the 17th Security Symposium"
    section = "2. Security Model"
    result = extract(cover, (b(cover, 100, 24),), {}, (
        PDFPageLayout(cover, (b(cover, 100, 24),), (600, 800)),
        PDFPageLayout(section, (b(section, 60, 18),), (600, 800)),
    ))
    assert result.metadata_sources["title"] == "filename fallback"
    assert result.review_reasons


@pytest.mark.parametrize("heading", [
    "1. Motivation: Distributed Computing", "2 Methods", "II. METHODS",
    "Keywords: access policies; authorization", "Content Warning: sensitive material",
    "CCS Concepts: Security and privacy", "Copyright 2026 Example Association",
    "ACM classification. K.6.5 Security and Protection",
    "∗Corresponding author", "Permission to reproduce this paper",
    "USENIX Association", "Network and Distributed System Security (NDSS) Symposium 2026",
])
def test_multi_paragraph_abstract_and_explicit_boundaries(heading):
    text = "Abstract\n" + "\n\n".join(PARAGRAPHS) + f"\n{heading}\nUNRELATED BODY"
    result = extract(text)
    assert result.abstract == " ".join(PARAGRAPHS)
    assert result.introduction_excerpt is None


def test_continuation_blocks_stop_at_centered_heading_and_other_column():
    blocks = (
        b("Abstract—" + PARAGRAPHS[0], 180, 9, height=50),
        b(PARAGRAPHS[1], 235, 9, height=50),
        b(PARAGRAPHS[2], 290, 9, height=50),
        b("I. INTRODUCTION", 350, 10, x=130, width=85),
        b("UNRELATED LEFT COLUMN " * 8, 380, height=70),
        b("UNRELATED RIGHT COLUMN " * 8, 180, x=320, height=100),
    )
    # Text order may visit the second column before the first column's boundary.
    text = "\n".join(block.text for block in (blocks[5], *blocks[:5]))
    assert extract(text, blocks).abstract == " ".join(PARAGRAPHS)


def test_unlabeled_cover_summary_keeps_all_paragraphs_without_intro_on_page_one():
    paragraphs = tuple(p * 2 for p in PARAGRAPHS)
    blocks = (b(TITLE, 60, 18, width=500), b("Alice Example\nExample University", 100, 12),
              *(b(p, 200 + i * 65, 10, width=480, height=60)
                for i, p in enumerate(paragraphs)),
              b("∗An abridged version appears elsewhere", 720, 8))
    result = extract("\n".join(block.text for block in blocks), blocks)
    assert result.abstract == " ".join(paragraphs)
    assert result.introduction_excerpt is None


def test_unlabeled_prose_requires_front_matter_evidence():
    blocks = (b(TITLE, 60, 18, width=500), b(PARAGRAPHS[0] * 2, 200))
    assert extract("", blocks).abstract is None


def test_unlabeled_body_after_a_section_is_not_promoted_to_abstract():
    blocks = (b(TITLE, 60, 18, width=500), b("Example University", 100),
              b("1. Motivation", 150), b(PARAGRAPHS[0] * 2, 200))
    assert extract("", blocks).abstract is None


@pytest.mark.parametrize("label", ["Keywords:", "Index Terms—", "Key words:"])
@pytest.mark.parametrize("separator", [",", ";", "·"])
def test_wrapped_keywords_are_complete_and_split(label, separator):
    text = (f"{label}delegated authorization{separator} Attribute-based en-\n"
            f"cryption{separator} token security\n1\nIntroduction\nUNRELATED BODY")
    assert extract(text).keywords == ["delegated authorization", "Attribute-based encryption",
                                     "token security"]


def test_keyword_layout_continuation_and_centered_boundary():
    blocks = (b("Keywords: authentication,", 200), b("access policies; token security", 222),
              b("1 INTRODUCTION", 250, x=130, width=100), b("UNRELATED BODY", 275))
    assert extract("", blocks).keywords == ["authentication", "access policies", "token security"]


def test_bilingual_keywords_do_not_consume_second_title():
    blocks = (b("キーワード：認証、セッション", 200), b("Second Language Title", 230, 16),
              b("Abstract: " + PARAGRAPHS[0], 280, height=50),
              b("Keywords: authentication, sessions", 345), b("1 Introduction", 375))
    result = extract("\n".join(block.text for block in blocks), blocks)
    assert result.keywords == ["認証", "セッション", "authentication", "sessions"]


def test_keywords_in_body_response_template_are_not_metadata():
    result = extract(f"Abstract\n{PARAGRAPHS[0]}\n1 Introduction\n{PARAGRAPHS[1]}\n"
                     "2 Method\nResponse template\nKeywords: detected, the conclu-\nResult: alert")
    assert result.keywords == []


def test_formal_pdf_keywords_are_used_without_inference():
    assert extract("", metadata={"title": TITLE, "keywords": "access control; delegation"}
                   ).keywords == ["access control", "delegation"]
    assert extract("").keywords == []


def test_dangling_keyword_fragment_is_not_returned_as_a_complete_word():
    assert extract("Keywords: access policies, en-\n1 Introduction").keywords == []


@pytest.mark.parametrize("noise", [
    "Authors’ addresses: Alice Example, Example University\nCity, XY 12345\nalice@example.org",
    "Department of Computer Science\nExample University\nCity, XY 12345\nalice@example.org",
    "∗Work carried out at Example Institute", "Email: alice@example.org",
    "Copyright 2026 Example Association\nAll Rights Reserved",
    "arXiv:2401.12345v1 [cs.CR] 1 Jan 2024",
])
def test_introduction_fallback_stops_before_contact_and_footnote_noise(noise):
    result = extract(f"1 Introduction\n{PARAGRAPHS[0]}\n{noise}\n2 Methods\nUNRELATED BODY")
    assert result.abstract is None
    assert result.introduction_excerpt == PARAGRAPHS[0]


def test_noisy_abstract_cannot_pass_gate_using_unused_introduction():
    # The provider sends only abstract when it exists, so fallback must not
    # validate a request whose actual classification text is unusable.
    assert classification_input_issues(title=TITLE, abstract="short",
                                       introduction_excerpt=PARAGRAPHS[0])


def test_wrapped_intro_prose_mentioning_a_university_is_preserved():
    text = ("1 Introduction\nOur study evaluates university policies for web\n"
            "authentication in distributed applications. " + PARAGRAPHS[0] + "\n2 Methods")
    assert extract(text).introduction_excerpt.startswith("Our study evaluates university policies")


def test_legitimate_titles_with_arxiv_and_internal_word_remain_usable():
    for title in ["Studying arXiv Identifier Use in Digital Libraries", "Main Memory Security",
                  "A Study of Proceedings Metadata", "Submission Policies for Web Services",
                  "Paper-based", "Draft-Proofing"]:
        assert not classification_input_issues(title=title, abstract=PARAGRAPHS[0],
                                               introduction_excerpt=None)


def test_parser_keeps_only_two_layout_pages_and_respects_max_pages(tmp_path: Path):
    path = tmp_path / "synthetic.pdf"
    with fitz.open() as pdf:
        for number in range(3):
            pdf.new_page().insert_text((72, 72), f"Page {number + 1}")
        pdf.save(path)
    parsed = parse_pdf(path, tmp_path)
    assert len(parsed.page_layouts) == 2
    assert parsed.page_layouts[0].blocks == parsed.first_page_blocks
    assert "Page 3" in parsed.text
    parsed = parse_pdf(path, tmp_path, max_pages=1)
    assert len(parsed.page_layouts) == 1
    assert "Page 2" not in parsed.text
