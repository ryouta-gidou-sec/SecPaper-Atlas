"""Conservative bibliographic extraction from PDF properties and first-page layout."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from src.models import ExtractedMetadata
from src.pdf_parser import PDFTextBlock, ParsedPDF


ABSTRACT_RE = re.compile(
    r"(?im)^[ \t]*(?:abstract(?![A-Za-z0-9_])|概要|要旨|あらまし)"
    r"[ \t]*[:：\-–—]?[ \t]*"
)
KEYWORD_RE = re.compile(
    r"(?im)^[ \t]*(?:keywords?(?![A-Za-z0-9_])|key[ \t]+words?(?![A-Za-z0-9_])|"
    r"index[ \t]+terms?(?![A-Za-z0-9_])|キーワード)[ \t]*[:：\-–—]?[ \t]*"
)
INTRO_RE = re.compile(
    r"(?im)^[ \t]*(?:(?:\d{1,2}(?:\.\d+)*[.)]?[ \t]*(?:\n[ \t]*)?)"
    r")?(?:introduction(?![A-Za-z0-9_])|"
    r"はじめに)[ \t]*[：:]?[ \t]*"
)
SECTION_RE = re.compile(
    r"(?im)^[ \t]*\d{1,2}(?:\.\d+)*[.)]?(?:[ \t]+\n?[ \t]*|\n[ \t]*)"
    r"[A-Za-z\u3040-\u30ff\u3400-\u9fff][^\n]{0,100}$"
)
ABSTRACT_STOP_RE = re.compile(
    r"(?im)^[ \t]*(?:keywords?(?![A-Za-z0-9_])|key[ \t]+words?(?![A-Za-z0-9_])|"
    r"index[ \t]+terms?(?![A-Za-z0-9_])|キーワード|categories and subject descriptors|"
    r"general terms|abstract(?![A-Za-z0-9_])|概要|要旨|あらまし|"
    r"introduction(?![A-Za-z0-9_])|はじめに|"
    r"\d{1,2}(?:\.\d+)*[.)]?(?:[ \t]+\n?[ \t]*|\n[ \t]*)"
    r"(?:introduction(?![A-Za-z0-9_])|はじめに))"
)
AFFILIATION_RE = re.compile(
    r"(?i)\b(?:university|institute|department|faculty|school|laboratory|lab\.?|"
    r"campus|company|corp\.?|inc\.?|department|cispa|saarland|keio|samsung|"
    r"sap se)\b|大学|大学院|研究科|学部|研究所|情報基盤|センター|機構"
)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def extract_metadata(parsed: ParsedPDF, filename: str) -> ExtractedMetadata:
    """Extract fields only when a page or metadata signal supports them.

    The first page is used for layout-sensitive fields. PDF creation dates are
    intentionally not treated as publication years.
    """

    first_page = parsed.first_page_text or parsed.text[:12000]
    blocks = tuple(parsed.first_page_blocks)
    page_height = parsed.first_page_size[1] if parsed.first_page_size else None
    title, title_blocks, title_source = _extract_title(parsed.metadata, blocks, page_height)
    title_bottom = max((item.y1 for item in title_blocks), default=0.0)

    authors, authors_source = _extract_authors(parsed.metadata, blocks, title_bottom)
    abstract, abstract_source = _extract_labeled_abstract(first_page, blocks)
    if not abstract and parsed.text and parsed.text != first_page:
        abstract, abstract_source = _extract_labeled_abstract(parsed.text, blocks)
        if abstract and abstract_source == "first page text":
            abstract_source = "bounded PDF text fallback"
    if not abstract:
        abstract = _extract_unlabeled_abstract(blocks, title_bottom)
        if abstract:
            abstract_source = "first page layout fallback"

    keywords = _extract_keywords(first_page)
    keywords_source = "first page text" if keywords else None
    if not keywords and blocks:
        keywords = _extract_keywords("", blocks)
        keywords_source = "first page layout" if keywords else None
    if not keywords and parsed.text and parsed.text != first_page:
        keywords = _extract_keywords(parsed.text)
        keywords_source = "bounded PDF text fallback" if keywords else None
    year, year_source = _extract_year(parsed.metadata, first_page, blocks)
    venue, venue_source = _extract_venue(parsed.metadata, first_page, blocks)

    introduction = None
    intro_source = None
    if not abstract:
        introduction = _extract_introduction(first_page)
        if introduction:
            intro_source = "first page text fallback"
        if not introduction:
            introduction = _extract_introduction_from_blocks(blocks)
            if introduction:
                intro_source = "first page layout fallback"

    metadata_sources: dict[str, str] = {}
    for field, source in (
        ("title", title_source),
        ("authors", authors_source),
        ("year", year_source),
        ("venue", venue_source),
        ("abstract", abstract_source),
        ("keywords", keywords_source),
        ("introduction_excerpt", intro_source),
    ):
        if source:
            metadata_sources[field] = source

    review_reasons: list[str] = []
    if title_source == "filename fallback":
        review_reasons.append("A reliable title was not found in PDF metadata or first-page layout.")
    if not abstract and not introduction:
        review_reasons.append("Neither an abstract nor an introduction excerpt was found.")
    if abstract and _looks_like_diagram_or_noise(abstract):
        review_reasons.append("The extracted abstract may contain figure or layout noise.")

    return ExtractedMetadata(
        title=title or _safe_title_from_filename(filename),
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract,
        keywords=keywords,
        introduction_excerpt=introduction,
        metadata_sources=metadata_sources,
        review_reasons=review_reasons,
    )


def classification_input_issues(
    *, title: str | None, abstract: str | None, introduction_excerpt: str | None
) -> list[str]:
    """Return reasons to hold a record before disclosing poor inputs to an API."""

    issues: list[str] = []
    normalized_title = " ".join((title or "").split())
    if len(normalized_title) < 8 or _is_bad_title(normalized_title):
        issues.append("A trustworthy title is required before classification.")
    if abstract and len(abstract.strip()) >= 80 and not _looks_like_diagram_or_noise(abstract):
        return issues
    if introduction_excerpt and len(introduction_excerpt.strip()) >= 120:
        return issues
    issues.append("A usable abstract or bounded introduction excerpt is required.")
    return issues


def _extract_title(
    metadata: dict[str, str],
    blocks: tuple[PDFTextBlock, ...],
    page_height: float | None,
) -> tuple[str | None, tuple[PDFTextBlock, ...], str | None]:
    layout_title, title_blocks = _layout_title(blocks, page_height)
    if layout_title:
        return layout_title, title_blocks, "first page layout"

    metadata_title = _clean_title(metadata.get("title", ""))
    if metadata_title:
        return metadata_title, (), "PDF metadata"

    return None, (), "filename fallback"


def _layout_title(
    blocks: tuple[PDFTextBlock, ...], page_height: float | None
) -> tuple[str | None, tuple[PDFTextBlock, ...]]:
    if not blocks:
        return None, ()
    height = page_height or max((item.y1 for item in blocks), default=800.0)
    cutoff = height * 0.25
    candidates = [
        item
        for item in blocks
        if item.y0 <= cutoff and item.font_size >= 13.0 and _clean_title(item.text)
    ]
    if not candidates:
        return None, ()
    candidates.sort(key=lambda item: (item.y0, item.x0))
    largest_size = max(item.font_size for item in candidates)
    eligible = [item for item in candidates if item.font_size >= largest_size - 2.6]
    # The largest early title line wins; adjacent same-size blocks are joined to
    # support titles split across PDF text blocks.
    best = max(
        eligible,
        key=lambda item: item.font_size * 4 - (item.y0 / max(height, 1)) * 8,
    )
    selected = [best]
    for candidate in eligible:
        if candidate is best:
            continue
        gap = candidate.y0 - best.y1
        if -1.0 <= gap <= max(25.0, best.font_size * 2.2) and abs(
            candidate.font_size - best.font_size
        ) <= 2.6:
            selected.append(candidate)
    selected.sort(key=lambda item: (item.y0, item.x0))
    cleaned = [_clean_title(item.text) for item in selected]
    joined = " ".join(value for value in cleaned if value)
    joined = re.sub(
        r"(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[\u3040-\u30ff\u3400-\u9fff])",
        "",
        joined,
    )
    joined = re.sub(r"(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[A-Za-z])", "", joined)
    title = _clean_title(joined)
    if not title:
        return None, ()
    return title, tuple(selected)


def _clean_title(value: str) -> str | None:
    cleaned = _normalize_text(value).strip(" \t\r\n-–—|:：")
    cleaned = _normalize_text(value).strip(" \t\r\n-–—|:：⋆∗†‡*")
    if not cleaned or _is_bad_title(cleaned):
        return None
    if len(cleaned) < 5 or len(cleaned) > 300:
        return None
    if EMAIL_RE.search(cleaned) or cleaned.count("@"):
        return None
    if len(cleaned.split()) > 42:
        return None
    return cleaned


def _is_bad_title(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return bool(
        normalized.startswith(("reprinted from", "regular paper", "abstractproxy"))
        or re.match(r"^(?:abstract|keywords?|key words?|index terms?)\b", normalized)
        or "received:" in normalized
        or "accepted:" in normalized
        or normalized in {"unknown", "untitled", "paper"}
        or (len(normalized) < 28 and re.fullmatch(r"[\d\W_]+", normalized))
    )


def _extract_authors(
    metadata: dict[str, str], blocks: tuple[PDFTextBlock, ...], title_bottom: float
) -> tuple[list[str], str | None]:
    metadata_authors = _split_authors(metadata.get("author", ""))
    if metadata_authors:
        return metadata_authors, "PDF metadata"

    if not blocks:
        return [], None
    ordered = sorted(blocks, key=lambda item: (item.y0, item.x0))
    stop_y = min(
        (item.y0 for item in ordered if _is_abstract_or_section_heading(item.text)),
        default=title_bottom + 150.0,
    )
    candidates: list[str] = []
    for block in ordered:
        if block.y0 < title_bottom - 1 or block.y0 >= stop_y or block.y0 > title_bottom + 180:
            continue
        text = _normalize_text(block.text)
        if not text:
            continue
        if EMAIL_RE.search(text) or _looks_like_affiliation(text):
            if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text):
                continue
            if re.match(
                r"(?i)^(?:national|nanyang|university|department|faculty|institute|"
                r"college|laboratory|lab\b|school|information processing society)\b",
                text.lstrip(" †‡⋆∗*"),
            ):
                continue
            # Some English author blocks put the name before an affiliation in
            # the same text box; retain only the leading name portion.
            leading = re.split(
                r"(?i)\b(?:CISPA|Saarland|University|Institute|Department|SAP SE)\b|"
                r"大学|大学院|研究科|学部|情報基盤|センター|機構",
                EMAIL_RE.sub("", text),
                maxsplit=1,
            )[0].strip()
            if not leading or not _looks_like_author_candidate(leading):
                continue
            text = leading
        if block.y0 > title_bottom + 70.0:
            continue
        if _looks_like_author_candidate(text):
            candidates.extend(_split_authors(text))
    authors = _dedupe(candidates)
    return authors, "first page layout" if authors else None


def _split_authors(value: str) -> list[str]:
    cleaned = EMAIL_RE.sub("", value)
    cleaned = re.sub(r"\([^)]*@[^)]*\)", "", cleaned)
    marked_names = re.findall(
        r"([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3})\s*\d+\s*,?\s*[a-z]?\)?",
        cleaned,
    )
    if marked_names:
        return [item.strip() for item in _dedupe(marked_names) if _looks_like_author_name(item)]
    cleaned = re.sub(r"[†‡⋆∗*]+", " ", cleaned)
    cleaned = re.sub(r"\d+\s*,?\s*[a-z]\)?", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;，、&")
    if _looks_like_affiliation(cleaned):
        cleaned = re.split(
            r"(?i)\b(?:university|institute|department|faculty|school|lab\.?|campus|"
            r"cispa|saarland|sap se)\b|大学|大学院|研究科|学部|情報基盤|センター|機構",
            cleaned,
            maxsplit=1,
        )[0]
    parts = re.split(r"\s*(?:;|；|,|，|、|&|\band\b)\s*", cleaned, flags=re.I)
    results: list[str] = []
    for part in parts:
        part = part.strip(" .,;，、&")
        if not part:
            continue
        # Japanese and Chinese author rows commonly separate names with spaces.
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", part):
            results.extend(
                token.strip(" .,;，、†‡⋆*0123456789()")
                for token in re.split(r"\s+", part)
                if token.strip(" .,;，、†‡⋆*0123456789()")
            )
        else:
            results.append(part)
    return [item for item in _dedupe(results) if _looks_like_author_name(item)]


def _looks_like_author_candidate(value: str) -> bool:
    if not value or len(value) > 160 or EMAIL_RE.search(value):
        return False
    if re.search(r"(?i)received|accepted|copyright|regular paper|abstract|keywords", value):
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", value):
        return False
    if len(value.split()) > 28:
        return False
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value) and len(value) > 100:
        return False
    if re.match(r"(?i)^(?:national|nanyang|technological)\b", value.lstrip(" †‡⋆∗*")):
        return False
    if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value):
        tokens = re.findall(r"[A-Za-z][A-Za-z.'-]*", value)
        if len(tokens) < 2:
            return False
    return any(char.isalpha() or "\u3040" <= char <= "\u9fff" for char in value)


def _looks_like_author_name(value: str) -> bool:
    if not value or len(value) > 80 or _looks_like_affiliation(value):
        return False
    if re.search(r"(?i)@|received|accepted|copyright|http|www\.", value):
        return False
    if re.match(r"(?i)^(?:national|nanyang|technological)\b", value):
        return False
    if len(value) < 2 or len(value.split()) > 5:
        return False
    if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value):
        if len(re.findall(r"[A-Za-z][A-Za-z.'-]*", value)) < 2:
            return False
    return bool(re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", value))


def _extract_labeled_abstract(
    text: str, blocks: tuple[PDFTextBlock, ...]
) -> tuple[str | None, str | None]:
    candidates: list[tuple[str, str]] = []
    sources = [(text, "first page text"), *((item.text, "first page layout") for item in blocks)]
    for source_text, source_name in sources:
        for match in ABSTRACT_RE.finditer(source_text):
            body = source_text[match.end() :]
            body = _cut_at_first(body, ABSTRACT_STOP_RE)
            cleaned = _clean_body(body)
            minimum_length = 20 if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", cleaned) else 40
            if len(cleaned) >= minimum_length and not _looks_like_diagram_or_noise(cleaned):
                candidates.append((cleaned[:6000].strip(), source_name))
    if not candidates:
        return None, None
    return max(
        candidates,
        key=lambda item: (
            _ascii_letter_ratio(item[0]) >= 0.35,
            item[1] == "first page layout",
            len(item[0]),
        ),
    )


def _extract_unlabeled_abstract(
    blocks: tuple[PDFTextBlock, ...], title_bottom: float
) -> str | None:
    ordered = sorted(blocks, key=lambda item: (item.y0, item.x0))
    intro = next((item for item in ordered if _is_intro_heading(item.text)), None)
    if intro is None:
        return None
    candidates = [
        item
        for item in ordered
        if item.y0 >= title_bottom
        and item.y0 < intro.y0
        and len(_clean_body(item.text)) >= 180
        and not _looks_like_affiliation(item.text)
        and not _is_abstract_or_section_heading(item.text)
        and not _looks_like_diagram_or_noise(item.text)
    ]
    if not candidates:
        return None
    # When Japanese and English summaries are both present, prefer the English
    # paragraph for the current English-language classifier input.
    chosen = max(
        candidates,
        key=lambda item: (
            _ascii_letter_ratio(item.text) >= 0.35,
            len(_clean_body(item.text)),
        ),
    )
    return _clean_body(chosen.text)[:6000] or None


def _extract_keywords(text: str, blocks: tuple[PDFTextBlock, ...] = ()) -> list[str]:
    values: list[str] = []
    for source_text in (text, *(item.text for item in blocks)):
        for match in KEYWORD_RE.finditer(source_text):
            tail = source_text[match.end() :]
            next_heading = min(
                (candidate.start() for candidate in _next_keyword_stop().finditer(tail)),
                default=len(tail),
            )
            candidate = tail[:next_heading].strip()
            if not candidate:
                for line in tail.splitlines():
                    if line.strip():
                        candidate = line.strip()
                        break
            candidate = candidate.splitlines()[0].strip() if candidate else ""
            candidate = re.sub(r"^(?:[:：]\s*)", "", candidate)
            candidate = re.sub(r"(?i)\b(?:keywords?|key words?|index terms?)\b", "", candidate)
            values.extend(re.split(r"\s*(?:,|;|，|；|、|\|)\s*", candidate))
    return [item.strip(" .。:：") for item in _dedupe(values) if len(item.strip()) <= 100]


def _next_keyword_stop() -> re.Pattern[str]:
    return re.compile(
        r"(?im)^[ \t]*(?:abstract(?![A-Za-z0-9_])|概要|要旨|あらまし|"
        r"introduction(?![A-Za-z0-9_])|はじめに|\d+(?:\.\d+)*[.)]?[ \t]+)"
    )


def _extract_introduction(text: str) -> str | None:
    match = INTRO_RE.search(text)
    if not match:
        return None
    body = text[match.end() :]
    body = _cut_at_first(body, SECTION_RE)
    cleaned = _clean_body(body)
    return cleaned[:2500].strip() if len(cleaned) >= 80 else None


def _extract_introduction_from_blocks(blocks: tuple[PDFTextBlock, ...]) -> str | None:
    ordered = sorted(blocks, key=lambda item: (item.y0, item.x0))
    start = next((index for index, item in enumerate(ordered) if _is_intro_heading(item.text)), None)
    if start is None:
        return None
    parts: list[str] = []
    for block in ordered[start:]:
        if block is not ordered[start] and SECTION_RE.match(block.text.strip()):
            break
        value = INTRO_RE.sub("", block.text, count=1).strip() if block is ordered[start] else block.text
        if value:
            parts.append(value)
    cleaned = _clean_body("\n".join(parts))
    return cleaned[:2500].strip() if len(cleaned) >= 80 else None


def _extract_year(
    metadata: dict[str, str], text: str, blocks: tuple[PDFTextBlock, ...]
) -> tuple[int | None, str | None]:
    lines = _front_page_lines(text, blocks)
    scored: list[tuple[int, int, str]] = []
    for line in lines:
        lower = line.casefold()
        if re.search(r"received|accepted|submitted|revised|accessed", lower):
            continue
        candidates = re.findall(r"\b(?:19|20)\d{2}\b", line)
        for raw_year in candidates:
            year = int(raw_year)
            score = 0
            if re.search(r"(?i)\b(?:vol\.?\s*\d|\d+\s*\(\s*\d+\s*\)\s*:)", line):
                score += 5
            if re.search(r"(?i)\b(?:WWW|Computer Security Symposium|Proceedings|Conference)\b", line):
                score += 5
            if re.search(r"情報処理学会第\d+回全国大会|コンピュータソフトウェア", line):
                score += 5
            if re.search(r"(?i)copyright|©|\(c\)", line):
                score += 4
            if re.search(r"(?i)^published\s*[:：]?\s*20\d{2}\b", line):
                score += 4
            if re.search(r"(?i)arxiv:\S+.*\b\d{1,2}\s+[A-Za-z]{3}\s+20\d{2}\b", line):
                score += 4
            if score:
                scored.append((score, year, line))
    if not scored:
        return None, None
    score, year, _ = max(scored, key=lambda item: (item[0], item[1]))
    return (year, "first page publication context") if score >= 4 else (None, None)


def _extract_venue(
    metadata: dict[str, str], text: str, blocks: tuple[PDFTextBlock, ...]
) -> tuple[str | None, str | None]:
    lines = _front_page_lines(text, blocks)
    for line in lines:
        normalized = " ".join(line.split())
        lower = normalized.casefold()
        if lower.startswith("reprinted from"):
            continue
        if re.search(r"(?i)\bInformation and Media Technologies\b", normalized):
            return "Information and Media Technologies", "first page journal header"
        journal = re.search(
            r"(?i)^(.{3,120}?)\s*,?\s*(?:vol\.?\s*\d+|\d+\s*\(\s*\d+\s*\)\s*:)",
            normalized,
        )
        if journal:
            venue = journal.group(1).strip(" ,;:-")
            if not _looks_like_affiliation(venue) and "reprinted" not in venue.casefold():
                return venue, "first page journal header"
        conference = re.search(r"Computer Security Symposium", normalized, re.I)
        if conference:
            return conference.group(0), "first page proceedings header"
        ipsj = re.search(r"情報処理学会第\d+回全国大会", normalized)
        if ipsj:
            return ipsj.group(0), "first page proceedings header"
        if re.search(r"\bWWW\s+20\d{2}\b", normalized):
            return "WWW", "first page proceedings footer"

    # PDF /Subject is often a generic description. Accept it only when it
    # corroborates an explicit journal or conference string on the page.
    subject = _normalize_text(metadata.get("subject", ""))
    if subject and any(subject.casefold() in line.casefold() for line in lines):
        return subject[:180], "PDF metadata corroborated by first page"
    return None, None


def _front_page_lines(text: str, blocks: tuple[PDFTextBlock, ...]) -> list[str]:
    values = [line.strip() for line in text.splitlines() if line.strip()]
    for block in blocks:
        values.extend(line.strip() for line in block.text.splitlines() if line.strip())
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _is_abstract_or_section_heading(value: str) -> bool:
    return bool(ABSTRACT_RE.match(value) or INTRO_RE.match(value) or SECTION_RE.match(value.strip()))


def _is_intro_heading(value: str) -> bool:
    return bool(INTRO_RE.match(value.strip()))


def _looks_like_affiliation(value: str) -> bool:
    return bool(AFFILIATION_RE.search(value) or EMAIL_RE.search(value))


def _looks_like_diagram_or_noise(value: str) -> bool:
    normalized = value.casefold()
    if "abstractproxy" in normalized or "httpxproxy" in normalized:
        return True
    diagram_label = re.compile(r"\bactivate\s*\(\)\s*close\s*\(\)\s*proxy\b")
    return len(diagram_label.findall(normalized)) >= 2


def _clean_body(value: str) -> str:
    cleaned = value.replace("\x00", " ").replace("\ufeff", " ")
    cleaned = re.sub(r"([A-Za-z])[-‐‑]\s*\n\s*([a-z])", r"\1\2", cleaned)
    cleaned = re.sub(r"[\t\r]+", " ", cleaned)
    cleaned = re.sub(r" *\n+ *", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _normalize_text(value: str) -> str:
    cleaned = value.replace("\u00a0", " ").replace("\x00", " ")
    cleaned = re.sub(r"([A-Za-z])[-‐‑]\s*\n\s*([a-z])", r"\1\2", cleaned)
    return " ".join(cleaned.split())


def _cut_at_first(value: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(value)
    return value[: match.start()] if match else value


def _safe_title_from_filename(filename: str) -> str:
    title = Path(filename).stem.replace("_", " ").replace("-", " ")
    title = " ".join(title.split())
    return title[:250] or "Unknown paper"


def _ascii_letter_ratio(value: str) -> float:
    letters = [char for char in value if char.isalpha()]
    return sum(1 for char in letters if ord(char) < 128) / max(len(letters), 1)


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(value.split()).strip(" ,;，、†‡⋆*")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
