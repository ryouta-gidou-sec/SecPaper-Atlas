from __future__ import annotations

import pytest

from src.metadata_extractor import classification_input_issues, extract_metadata
from src.pdf_parser import PDFTextBlock, ParsedPDF


def block(text: str, y: float, font_size: float = 10.0, x: float = 50.0) -> PDFTextBlock:
    return PDFTextBlock(text=text, x0=x, y0=y, x1=x + 500, y1=y + 18, font_size=font_size)


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


def test_layout_prefers_english_title_and_splits_multiple_authors() -> None:
    parsed = ParsedPDF(
        text="ABSTRACT\nA sufficiently descriptive abstract about authentication and session attacks. " * 3,
        first_page_text=(
            "ABSTRACT\nA sufficiently descriptive abstract about authentication and session attacks. "
            "The work evaluates multiple applications and reports its results.\n1 INTRODUCTION"
        ),
        metadata={},
        page_count=1,
        first_page_blocks=(
            block("A Practical Study of Web Authentication", 80, 18),
            block("Alice Example, Bob Researcher and Carol Analyst", 119, 12),
            block("ABSTRACT", 180, 11),
        ),
        first_page_size=(600, 800),
    )
    result = extract_metadata(parsed, "paper.pdf")
    assert result.title == "A Practical Study of Web Authentication"
    assert result.authors == ["Alice Example", "Bob Researcher", "Carol Analyst"]
    assert result.metadata_sources["title"] == "first page layout"


def test_extracts_japanese_title_and_multiple_japanese_authors() -> None:
    parsed = ParsedPDF(
        text="概要：Webサービスの安全性を調べる研究である。複数の実験結果を示す。",
        first_page_text="概要：Webサービスの安全性を調べる研究である。複数の実験結果を示す。",
        metadata={},
        page_count=1,
        first_page_blocks=(
            block("Webサービスにおけるセッション安全性の研究", 90, 18),
            block("山田太郎† 鈴木花子‡", 125, 12),
            block(
                "概要：Webサービスの安全性を調べる研究である。複数の実験結果を示し、評価した。",
                180,
                10,
            ),
        ),
        first_page_size=(600, 800),
    )
    result = extract_metadata(parsed, "paper.pdf")
    assert result.title == "Webサービスにおけるセッション安全性の研究"
    assert result.authors == ["山田太郎", "鈴木花子"]
    assert result.abstract is not None


@pytest.mark.parametrize(
    ("heading", "body"),
    [
        ("Abstract", "This paper studies session security and evaluates a set of web applications."),
        ("概要：", "Webサービスの認証を対象に複数の実験を行い、安全性を評価した。"),
        ("要旨：", "本研究では認証方式を調査し、実験結果とその有効性を報告する。"),
        ("あらまし", "Webアプリケーションのセッション管理を対象として評価を実施した。"),
    ],
)
def test_recognizes_english_and_japanese_abstract_headings(heading: str, body: str) -> None:
    separator = "\n" if heading == "Abstract" else ""
    if heading != "Abstract":
        body += "研究の目的と手法を説明し、実験による評価結果について報告する。"
    first_page = f"A Reliable Paper Title\n{heading}{separator}{body}\n1 はじめに\nBody after abstract"
    result = extract_metadata(
        ParsedPDF(first_page, first_page, {"title": "A Reliable Paper Title"}, 1),
        "paper.pdf",
    )
    assert result.abstract is not None
    assert "Body after abstract" not in result.abstract


def test_abstractproxy_is_not_treated_as_an_abstract_heading() -> None:
    text = (
        "A Reliable Paper Title\nAbstractProxy handles diagram drawing.\n"
        "1 Introduction\nThe introduction is not an abstract."
    )
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract is None


@pytest.mark.parametrize("heading", ["1 Introduction", "1. はじめに"])
def test_abstract_ends_before_introduction(heading: str) -> None:
    text = (
        "Abstract\nThis is a sufficiently detailed abstract describing a system and its evaluation. "
        "It reports findings from several experiments and discusses their implications.\n"
        f"{heading}\nINTRODUCTION BODY THAT MUST NOT BE INCLUDED"
    )
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract is not None
    assert "INTRODUCTION BODY" not in result.abstract


def test_introduction_fallback_ends_at_next_japanese_section() -> None:
    text = (
        "1 はじめに\n" + "この研究ではセッション安全性を評価するための方法を説明する。 " * 12
        + "\n2 実験\nEXPERIMENT SECTION MUST NOT BE INCLUDED"
    )
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract is None
    assert result.introduction_excerpt is not None
    assert "EXPERIMENT SECTION" not in result.introduction_excerpt


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Keywords: alpha, beta; gamma", ["alpha", "beta", "gamma"]),
        ("Key words - alpha; beta", ["alpha", "beta"]),
        ("Index Terms—alpha, beta", ["alpha", "beta"]),
        ("キーワード：認証、セッション管理", ["認証", "セッション管理"]),
    ],
)
def test_keyword_heading_and_delimiter_variants(line: str, expected: list[str]) -> None:
    text = f"A Reliable Paper Title\n{line}\n1 Introduction"
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.keywords == expected


def test_publication_year_and_venue_ignore_creation_date_and_reprint_line() -> None:
    text = (
        "Information and Media Technologies 8(2): 594-604 (2013)\n"
        "reprinted from: IPSJ Transactions on Advanced Computing Systems 6(1) (2011)\n"
        "Received: 2012, Accepted: 2012"
    )
    result = extract_metadata(
        ParsedPDF(
            text,
            text,
            {"creationDate": "D:20170830002108Z", "subject": "generic PDF subject"},
            1,
        ),
        "paper.pdf",
    )
    assert result.year == 2013
    assert result.venue == "Information and Media Technologies"


def test_missing_metadata_uses_safe_filename_fallback_and_records_review() -> None:
    result = extract_metadata(
        ParsedPDF(text="", first_page_text="", metadata={}, page_count=0),
        "unknown_paper.pdf",
    )
    assert result.title == "unknown paper"
    assert result.abstract is None
    assert result.year is None
    assert result.authors == []
    assert result.metadata_sources["title"] == "filename fallback"
    assert result.review_reasons


def test_classification_quality_gate_holds_bad_title_and_empty_input() -> None:
    assert classification_input_issues(
        title="reprinted from a journal", abstract="A" * 200, introduction_excerpt=None
    )
    assert classification_input_issues(
        title="A Genuine Paper Title", abstract=None, introduction_excerpt=None
    )
    assert not classification_input_issues(
        title="A Genuine Paper Title", abstract="A useful abstract. " * 8, introduction_excerpt=None
    )


ABSTRACT_BODY = (
    "We evaluate authentication defenses across multiple web services and report "
    "reproducible findings from controlled security experiments."
)
INTRO_BODY = (
    "Web authentication protects access to private resources. This study examines "
    "deployed protocols and measures their security properties under realistic attacks."
)


@pytest.mark.parametrize(
    "heading", ["Abstract", "ABSTRACT", "abstract", "Abstract—", "Abstract:", "Summary", "SUMMARY:"]
)
def test_abstract_heading_variations_with_roman_section_boundary(heading: str) -> None:
    text = f"{heading}\n{ABSTRACT_BODY}\nI. INTRODUCTION\nUNRELATED INTRODUCTION BODY"
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract == ABSTRACT_BODY
    assert result.introduction_excerpt is None
    assert not result.review_reasons


@pytest.mark.parametrize(
    "heading",
    ["1 Introduction", "1. Introduction", "I. INTRODUCTION", "INTRODUCTION", "1\nIntroduction"],
)
@pytest.mark.parametrize("next_heading", ["2 Methods", "II. METHODS", "References"])
def test_introduction_heading_variations_and_boundaries(heading: str, next_heading: str) -> None:
    text = f"{heading}\n{INTRO_BODY}\n{next_heading}\nUNRELATED SECTION BODY"
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract is None
    assert result.introduction_excerpt == INTRO_BODY
    assert not result.review_reasons
    assert not classification_input_issues(
        title=result.title, abstract=None, introduction_excerpt=result.introduction_excerpt
    )


def test_bounded_introduction_fallback_skips_split_toc_entry() -> None:
    first_page = "A Reliable Paper Title\nA short unlabeled synopsis."
    toc = "Contents\n1\nIntroduction\n5\n2\nProtocol\n7"
    text = f"{first_page}\n\n{toc}\n\n1. Introduction\n{INTRO_BODY}\n2 Protocol\nUNRELATED BODY"
    result = extract_metadata(
        ParsedPDF(text, first_page, {"title": "A Reliable Paper Title"}, 8), "paper.pdf"
    )
    assert result.abstract is None
    assert result.introduction_excerpt == INTRO_BODY
    assert result.metadata_sources["introduction_excerpt"] == "bounded PDF text fallback"


def test_toc_alone_does_not_become_introduction_from_text_or_layout() -> None:
    text = "Contents\n1\nIntroduction\n5\n2\nMethods\n7\n" + "A long table entry. " * 12
    result = extract_metadata(
        ParsedPDF(
            text, text, {"title": "A Reliable Paper Title"}, 1,
            first_page_blocks=(
                block("1\nIntroduction\n5", 60), block("A long table entry. " * 12, 100)
            ),
        ),
        "paper.pdf",
    )
    assert result.abstract is None
    assert result.introduction_excerpt is None
    assert result.review_reasons


@pytest.mark.parametrize(
    "line",
    [
        "AbstractProxy is a software component.",
        "Abstract security concepts are discussed here.",
        "Summary of the recovery experiment",
        "Introduction of new functionality is discussed here.",
    ],
)
def test_prose_and_summary_subsection_names_are_not_front_matter(line: str) -> None:
    text = f"{line}\n{INTRO_BODY}"
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract is None
    assert result.introduction_excerpt is None


@pytest.mark.parametrize("section", ["1 Introduction", "2 Methods"])
def test_summary_after_body_sections_is_not_an_abstract(section: str) -> None:
    text = f"{section}\n{INTRO_BODY}\nSummary:\n{ABSTRACT_BODY}"
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract is None


@pytest.mark.parametrize("next_heading", ["2 Methods", "II. METHODS", "References"])
def test_summary_stops_at_body_section_even_without_introduction(next_heading: str) -> None:
    text = f"Summary\n{ABSTRACT_BODY}\n{next_heading}\nUNRELATED SECTION BODY"
    result = extract_metadata(
        ParsedPDF(text, text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.abstract == ABSTRACT_BODY


def test_abstract_and_introduction_keep_their_character_limits() -> None:
    abstract_text = "Abstract\n" + ABSTRACT_BODY * 60
    result = extract_metadata(
        ParsedPDF(abstract_text, abstract_text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert len(result.abstract) == 6000
    assert result.introduction_excerpt is None
    intro_text = "1 Introduction\n" + INTRO_BODY * 30 + "\n2 Methods\nUNRELATED BODY"
    result = extract_metadata(
        ParsedPDF(intro_text, intro_text, {"title": "A Reliable Paper Title"}, 1), "paper.pdf"
    )
    assert result.introduction_excerpt == (INTRO_BODY * 30)[:2500].strip()
    assert len(result.introduction_excerpt) <= 2500


def cover_blocks(branding: str) -> tuple[PDFTextBlock, ...]:
    # Actual covers use overlapping line boxes and multiple title blocks below
    # the normal top-quarter cutoff, followed by mixed author/affiliation rows.
    return (
        block("This paper is included in the Proceedings of the", 430, 18),
        block(branding, 455, 18),
        block("Controlled Security Experiments:", 228, 21),
        block("Evaluating Deployed", 244, 21),
        block("Authentication Systems", 260, 21),
        block("Alice Example, Example University; Bob Researcher, Example Institute", 290, 14),
    )


@pytest.mark.parametrize(
    "branding", ["33rd USENIX Security Symposium.", "https://www.usenix.org/conference/soups2023"]
)
def test_proceedings_cover_title_fallback_joins_overlapping_lines(branding: str) -> None:
    first_page = "\n".join(b.text for b in cover_blocks(branding))
    body_page = f"Abstract\n{ABSTRACT_BODY}\n1 Introduction\n{INTRO_BODY}"
    result = extract_metadata(
        ParsedPDF(
            first_page + "\n\n" + body_page, first_page, {}, 8,
            first_page_blocks=cover_blocks(branding), first_page_size=(612, 792),
        ),
        "ACCOUNT_01_download_label.pdf",
    )
    assert result.title == (
        "Controlled Security Experiments: Evaluating Deployed Authentication Systems"
    )
    assert result.metadata_sources["title"] == "first page cover layout"
    assert result.abstract == ABSTRACT_BODY
    assert result.authors == []  # Cover affiliations must not be guessed as author names.
    assert not result.review_reasons


def test_cover_fallback_preserves_existing_pdf_metadata_title_and_authors() -> None:
    blocks = cover_blocks("33rd USENIX Security Symposium.")
    text = f"Abstract\n{ABSTRACT_BODY}"
    result = extract_metadata(
        ParsedPDF(
            text, text, {"title": "Existing Metadata Title", "author": "Alice Example"}, 1,
            first_page_blocks=blocks, first_page_size=(612, 792),
        ),
        "paper.pdf",
    )
    assert result.title == "Existing Metadata Title"
    assert result.authors == ["Alice Example"]
    assert result.metadata_sources["title"] == "PDF metadata"


@pytest.mark.parametrize(
    "blocks", [cover_blocks("Unrelated Conference"), cover_blocks("USENIX Security Symposium")[2:]]
)
def test_cover_fallback_requires_both_signals(blocks: tuple[PDFTextBlock, ...]) -> None:
    text = f"Abstract\n{ABSTRACT_BODY}"
    result = extract_metadata(
        ParsedPDF(text, text, {}, 1, first_page_blocks=blocks, first_page_size=(612, 792)),
        "paper.pdf",
    )
    assert result.metadata_sources["title"] == "filename fallback"
