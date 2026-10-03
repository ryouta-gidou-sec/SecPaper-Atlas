"""Local, evidence-based author and publication extraction.

These rules are separate from the classification-input heuristics: changing a
bibliographic field must not change title, abstract, keywords or introduction.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from src.pdf_parser import PDFTextBlock


AFFILIATION = re.compile(
    r"(?i)\b(?:universit\w*|institute|institution|dept\.?|department|faculty|school|"
    r"college|laborator\w*|research|centre|center|campus|association|society|"
    r"conference|symposium|workshop|proceedings|corporation|company|corp\.?|inc\.?|"
    r"ltd\.?|llc|unaffiliated|informatics|engineering|computer science|"
    r"information security group|web services|agency|technology|CISPA|FORTH|Fraunhofer|"
    r"ETH|MIT|UC|SAP SE)\b|大学|大学院|研究科|学部|研究所|情報基盤|センター|機構"
)
ADDRESS = re.compile(
    r"(?i)\d{3,}|\b(?:street|road|avenue|postal|zip|address|USA|UK|Germany|"
    r"Norway|China|Indonesia)\b|https?://|www\.|@"
)
HEADING = re.compile(
    r"(?i)^\s*(?:abstract\b|summary\s*[:：]?$|概要|要旨|あらまし|"
    r"(?:\d{1,2}[.)]?\s*)?(?:introduction|はじめに)\b)"
)
PARTICLES = {"van", "von", "de", "der", "den", "del", "da", "di", "dos", "du", "le", "bin", "al"}
DATE_EXCLUSION = re.compile(
    r"(?i)arxiv|access(?:ed)?|retriev(?:ed|al)|download(?:ed)?|received|accepted|"
    r"submitted|revised|reprinted from|version of|abridged version|appears in|受付|受理"
)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
MONTH = re.compile(
    r"(?i)\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b"
)
ORDINAL = (
    r"(?:\d+(?:st|nd|rd|th)|First|Second|Third|Fourth|Fifth|Sixth|Seventh|"
    r"Eighth|Ninth|Tenth|Eleventh|Twelfth|Thirteenth|Fourteenth|Fifteenth|"
    r"Sixteenth|Seventeenth|Eighteenth|Nineteenth|Twentieth)"
)


def _clean_name(value: str) -> str:
    # Convert detached PDF accent glyphs, retaining the printed spelling.
    for glyph, combining in (("´", "\u0301"), ("`", "\u0300"), ("¨", "\u0308")):
        value = re.sub(re.escape(glyph) + r"([^\W\d_])", lambda m: m[1] + combining, value)
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\d+(?:\s*,\s*[a-z]\))?\s*(?:\([^)]{0,4}\))?", "", value)
    value = re.sub(r"[†‡⋆∗*§⁎⁑]+", "", value)
    value = value.replace("\x00", "").replace("\x0c", "")
    return " ".join(value.split()).strip(" ,;，、&().")


def _is_name(value: str) -> bool:
    if not value or len(value) > 80 or AFFILIATION.search(value) or ADDRESS.search(value):
        return False
    if re.search(r"(?i)\b(?:technical|copyright|published|abstract|keywords|security|"
                 r"independent|international|national|technology|computing|division)\b", value):
        return False
    if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value):
        return bool(re.fullmatch(r"[\u3040-\u30ff\u3400-\u9fff]{2,12}", value))
    tokens = value.split()
    return 2 <= len(tokens) <= 5 and all(
        token.casefold() in PARTICLES or (
            token[0].isupper() and all(char.isalpha() or char in ".'-’‐" for char in token)
        ) for token in tokens
    )


def _names(value: str) -> list[str]:
    # Split names before cleaning markers, so a surname's Unicode accent is
    # never lost to an ASCII-only surname expression or a marked-name shortcut.
    if re.search(r"\d{3,}|https?://|\b(?:street|road|avenue|postal|zip)\b", value, re.I):
        return []
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "", value)
    value = value.replace("<", "").replace(">", "")
    value = re.sub(r"\d+\s*,\s*[a-z]\)", "", value, flags=re.I)
    parts = re.split(r"\s*(?:[,;，；、&]|\band\b)\s*", value, flags=re.I)
    result = []
    for part in parts:
        if AFFILIATION.search(part):
            continue
        part = _clean_name(part)
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", part):
            result.extend(name for name in part.split() if _is_name(name))
        elif _is_name(part):
            result.append(part)
    return result


def _unique(names: list[str]) -> list[str]:
    return list(dict((name.casefold(), name) for name in names).values())


def extract_authors(
    metadata: dict[str, str], blocks: tuple[PDFTextBlock, ...], title_bottom: float
) -> tuple[list[str], str | None]:
    metadata_names = _unique(_names(metadata.get("author", "")))
    # Without title geometry, we cannot distinguish a title from author rows.
    if not blocks or not title_bottom:
        return metadata_names, "PDF metadata" if metadata_names else None
    stop_y = min((block.y0 for block in blocks if block.y0 >= title_bottom - 2 and (
        HEADING.match(block.text) or len(block.text) > 180
        and re.search(r"[.。．]", block.text) and not AFFILIATION.search(block.text)
    )), default=title_bottom + 300)
    names = []
    for block in sorted(blocks, key=lambda b: (b.y0, b.x0)):
        if block.direction[0] < .95 or abs(block.direction[1]) > .1:
            continue
        if block.y0 < title_bottom - 2 or block.y0 >= stop_y:
            continue
        lines = [(line.text, line.y0) for line in block.lines] if block.lines else [
            (line, block.y0) for line in block.text.splitlines()
        ]
        affiliation_seen, contact_seen = False, False
        pending = ""
        for raw, y in lines:
            if y >= stop_y or y > title_bottom + 300:
                continue
            inline = re.split(r"[,;]", raw, maxsplit=1)[0]
            # Inline name/affiliation rows and separate lines take different
            # routes; the first comma bounds the former's author field.
            if (AFFILIATION.search(raw) and _is_name(_clean_name(inline))
                    and not affiliation_seen):
                names.extend(_names(inline))
                continue
            if AFFILIATION.search(raw):
                affiliation_seen = True
                contact_seen = False
                pending = ""
                continue
            if ADDRESS.search(raw):
                contact_prefix = re.split(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", raw)[0]
                if "@" in raw and not affiliation_seen:
                    names.extend(_names(contact_prefix))
                contact_seen = "@" in raw
                pending = ""
                continue
            if affiliation_seen and not contact_seen:
                continue
            if not pending and "," in raw and _clean_name(inline) and not _is_name(_clean_name(inline)):
                affiliation_seen, contact_seen, pending = True, False, ""
                continue
            if pending:
                found = _names(pending + " " + raw)
                pending = ""
            else:
                found = _names(raw)
            if found:
                names.extend(found)
                affiliation_seen, contact_seen = False, False
            elif re.fullmatch(r"[^\W\d_]+", _clean_name(raw), re.UNICODE):
                pending = _clean_name(raw)
    layout_names = _unique(names)
    if layout_names:
        if {n.casefold() for n in layout_names} == {n.casefold() for n in metadata_names}:
            return metadata_names, "PDF metadata"
        return layout_names, "first page layout"
    return metadata_names, "PDF metadata" if metadata_names else None


def _publication_records(text: str, blocks: tuple[PDFTextBlock, ...]) -> list[str]:
    # Block joining handles split conference/journal headers. Text lines are
    # also retained for synthetic/text-only input, and split copyright notices.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records = list(lines)
    records.extend(" ".join(block.text.split()) for block in blocks
                   if block.direction[0] >= .95 and abs(block.direction[1]) <= .1)
    records.extend(" ".join(lines[i:i + 2]) for i in range(len(lines) - 1)
                   if len(lines[i]) < 160 and len(lines[i + 1]) < 160)
    return list(dict.fromkeys(records))


def _venue(value: str) -> tuple[str | None, str | None]:
    if (DATE_EXCLUSION.search(value) or re.match(r"\[\d+\]|\d+\.", value)
            or re.search(r"(?i)\b(?:we|our|evaluate|discuss|previous|cited|references|bibliography)\b", value)):
        return None, None
    patterns = (
        r"USENIX Security Symposium",
        r"Symposium on Usable Privacy and Security",
        r"Network and Distributed System Security\s*\(NDSS\)\s*Symposium",
        r"NDSS(?=\s+[’']?\d{2,4}\b)",
        r"ESORICS(?=\s+20\d{2}\b)",
        r"Computer Security Symposium",
        r"情報処理学会第\d+回全国大会",
        r"WWW(?=\s+20\d{2}\b)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, re.I)
        if match and len(value) <= 450:
            prefix = value[:match.start()].strip()
            if (not prefix or re.fullmatch(ORDINAL, prefix, re.I)
                    or re.search(r"(?i)proceedings(?: of)?(?: the)?\s*(?:" + ORDINAL + r")?$", prefix)
                    or re.search(r"(?i)\(Eds?\.\):$", prefix)):
                return match[0], "first page proceedings header"
    published_at = re.match(r"(?i)^(?:paper )?published (?:at|in)\s+(.{3,160}?)(?:\.|$)", value)
    if published_at:
        name = published_at[1].strip()
        if (not re.search(r"(?i)universit|institute|company|publisher|\bpress\b|copyright", name)
                and (re.search(r"(?i)conference|symposium|workshop|journal|proceedings", name)
                     or re.fullmatch(r"[A-Za-z][A-Za-z-]+\s+[’']?\d{2,4}", name))):
            return name, "first page publication header"
    journal = re.search(r"(?i)^(.{3,120}?)\s*,?\s*(?:vol\.?\s*\d+|\d+\s*\(\d+\)\s*:)", value)
    if journal:
        name = journal[1].strip(" ,;:-")
        if (not AFFILIATION.search(name) and not re.search(r"(?i)copyright|©|https?://", name)
                and re.search(r"(?i)\b(?:journal|jurnal|transactions|annals|letters|review|bulletin|magazine)\b|"
                              r"Information and Media Technologies|コンピュータソフトウェア", name)):
            return name, "first page journal header"
    proceedings = re.match(
        r"(?i)^(?:proceedings of (?:the )?|(?:\d+(?:st|nd|rd|th) )?)"
        r"([^\n]{3,150}?\b(?:conference|workshop|symposium)(?: on [^\n]{3,100})?)"
        r"(?:\s+\(?20\d{2}\)?|[.,]|$)", value,
    )
    if proceedings and not re.search(r"(?i)university|institute|company|copyright", proceedings[1]):
        name = proceedings[1].strip()
        connectors = {"on", "of", "the", "and", "in", "for", "conference", "symposium", "workshop"}
        if all(word.casefold() in connectors or word[0].isupper() for word in name.split()):
            return name, "first page proceedings header"
    return None, None


def extract_venue(
    metadata: dict[str, str], text: str, blocks: tuple[PDFTextBlock, ...]
) -> tuple[str | None, str | None]:
    records = _publication_records(text, blocks)
    # Full blocks before individual lines ensure the journal's name and volume
    # can corroborate one another even when typeset on different lines.
    for value in sorted(records, key=lambda v: not bool(re.search(r"(?i)\bvol\.?|\d+\(\d+\)", v))):
        venue, source = _venue(value)
        if venue:
            return venue, _publication_source(venue, source, text, blocks)
    # Generic /Subject strings and publisher-only properties are not venues.
    return None, None


def _publication_source(
    venue: str, source: str, text: str, blocks: tuple[PDFTextBlock, ...]
) -> str:
    if source != "first page proceedings header":
        return source
    if re.search(r"(?i)proceedings of (?:the|a)\b", text) and not any(
        HEADING.match(line) for line in text.splitlines()
    ):
        return "first page proceedings cover"
    containing = [b for b in blocks if venue.casefold() in " ".join(b.text.split()).casefold()]
    bottom = max((b.y1 for b in blocks), default=0)
    if containing and min(b.y0 for b in containing) > bottom * .65:
        return "first page proceedings footer"
    return source


def extract_year(
    metadata: dict[str, str], text: str, blocks: tuple[PDFTextBlock, ...]
) -> tuple[int | None, str | None]:
    candidates: list[tuple[int, int, str]] = []
    records = _publication_records(text, blocks)
    cover = bool(re.search(r"(?i)proceedings of (?:the|a)\b", text)) and not any(
        HEADING.match(line) for line in text.splitlines()
    )
    for value in records:
        # A Published field can coexist with Received/Accepted on one line.
        published = re.search(r"(?i)(?:^|;\s*)published\s*[:：]\s*(.*?)(?=;|copyright|©|$)", value)
        if published:
            candidates.extend((4, int(y), "first page publication header")
                              for y in YEAR.findall(published[1]))
        if DATE_EXCLUSION.search(value):
            continue
        years = {int(y) for y in YEAR.findall(value)}
        if not years:
            continue
        venue, source = _venue(value)
        if venue:
            source = _publication_source(venue, source, text, blocks)
            # Neighbor joining must not promote a following copyright year
            # to the priority of a journal/conference citation.
            publication = re.split(r"(?i)copyright|©|\(c\)", value, maxsplit=1)[0]
            years = {int(y) for y in YEAR.findall(publication)}
        priority = 0
        if source == "first page journal header":
            priority = 4
        elif venue:
            priority = 3
        elif re.match(r"(?i)^published\s*[:：]?\s*(?:19|20)\d{2}\b", value):
            priority, source = 4, "first page publication header"
        elif cover and MONTH.search(value) and len(value) < 140 and not re.search(r"(?i)copyright|©", value):
            priority, source = 3, "first page proceedings date"
        elif re.match(r"(?i)^(?:copyright|©|\(c\)|c\s*⃝)", value):
            priority, source = 1, "first page copyright line"
        if priority:
            candidates.extend((priority, y, source) for y in years)
    for key in ("year", "publicationyear", "publicationdate"):
        candidates.extend((2, year, "PDF metadata")
                          for year in _metadata_years(metadata.get(key, "")))
    if not candidates:
        return None, None
    priority = max(candidate[0] for candidate in candidates)
    best = [candidate for candidate in candidates if candidate[0] == priority]
    years = {candidate[1] for candidate in best}
    if len(years) != 1:
        return None, None
    return best[0][1], best[0][2]


def _metadata_years(value: str) -> set[int]:
    """Only explicit years or valid ISO publication dates cross this boundary."""
    years = set()
    for item in value.split(";"):
        item = item.strip()
        if not re.fullmatch(r"(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?(?:T[\d:.Z+\-]+)?", item):
            return set()
        try:
            if "T" in item:
                year = datetime.fromisoformat(item.replace("Z", "+00:00")).year
            elif len(item) == 10:
                year = date.fromisoformat(item).year
            elif len(item) == 7:
                year = date(int(item[:4]), int(item[5:]), 1).year
            else:
                year = int(item)
        except ValueError:
            return set()
        years.add(year)
    return years
