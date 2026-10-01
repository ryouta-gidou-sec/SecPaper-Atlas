"""SQLite persistence with normalized searchable classification labels."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from src.models import (
    ClassificationResult,
    ExtractedMetadata,
    PaperStatus,
    PrimaryCategory,
    Relevance,
)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_hash TEXT NOT NULL UNIQUE CHECK(length(file_hash) = 64),
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    title TEXT,
    authors_json TEXT NOT NULL DEFAULT '[]',
    year INTEGER CHECK(year IS NULL OR year BETWEEN 1900 AND 2100),
    venue TEXT,
    abstract TEXT,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    metadata_sources_json TEXT NOT NULL DEFAULT '{}',
    ai_primary_category TEXT CHECK(ai_primary_category IS NULL OR ai_primary_category IN (
        'Authentication', 'Session Management', 'Authorization', 'Token Security',
        'OAuth / OIDC / SSO', 'Account Management', 'Vulnerability Assessment', 'Other Security'
    )),
    primary_category TEXT CHECK(primary_category IS NULL OR primary_category IN (
        'Authentication', 'Session Management', 'Authorization', 'Token Security',
        'OAuth / OIDC / SSO', 'Account Management', 'Vulnerability Assessment', 'Other Security'
    )),
    ai_relevance TEXT CHECK(ai_relevance IS NULL OR ai_relevance IN ('A', 'B', 'C')),
    relevance TEXT CHECK(relevance IS NULL OR relevance IN ('A', 'B', 'C')),
    ai_relevance_reason TEXT,
    relevance_reason TEXT,
    ai_relevance_confidence REAL CHECK(
        ai_relevance_confidence IS NULL OR ai_relevance_confidence BETWEEN 0 AND 1
    ),
    relevance_confidence REAL CHECK(
        relevance_confidence IS NULL OR relevance_confidence BETWEEN 0 AND 1
    ),
    status TEXT NOT NULL DEFAULT 'Unread'
        CHECK(status IN ('Unread', 'Screened', 'Read', 'Important')),
    manually_reviewed INTEGER NOT NULL DEFAULT 0 CHECK(manually_reviewed IN (0, 1)),
    classification_error TEXT,
    processing_seconds REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS research_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS vulnerabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS paper_tags (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    value_source TEXT NOT NULL CHECK(value_source IN ('ai', 'current')),
    PRIMARY KEY (paper_id, tag_id, value_source)
);
CREATE TABLE IF NOT EXISTS paper_methods (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    method_id INTEGER NOT NULL REFERENCES research_methods(id) ON DELETE CASCADE,
    value_source TEXT NOT NULL CHECK(value_source IN ('ai', 'current')),
    PRIMARY KEY (paper_id, method_id, value_source)
);
CREATE TABLE IF NOT EXISTS paper_vulnerabilities (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    vulnerability_id INTEGER NOT NULL REFERENCES vulnerabilities(id) ON DELETE CASCADE,
    value_source TEXT NOT NULL CHECK(value_source IN ('ai', 'current')),
    PRIMARY KEY (paper_id, vulnerability_id, value_source)
);

CREATE INDEX IF NOT EXISTS idx_papers_category ON papers(primary_category);
CREATE INDEX IF NOT EXISTS idx_papers_relevance ON papers(relevance);
CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_paper_tags_source ON paper_tags(value_source, tag_id);
CREATE INDEX IF NOT EXISTS idx_paper_methods_source ON paper_methods(value_source, method_id);
CREATE INDEX IF NOT EXISTS idx_paper_vulnerabilities_source
    ON paper_vulnerabilities(value_source, vulnerability_id);
"""

LABEL_TABLES = {
    "tags": ("tags", "paper_tags", "tag_id"),
    "research_methods": ("research_methods", "paper_methods", "method_id"),
    "target_vulnerabilities": (
        "vulnerabilities",
        "paper_vulnerabilities",
        "vulnerability_id",
    ),
}


class DuplicatePaperError(RuntimeError):
    """Raised when a file hash already exists."""


class Database:
    """Small repository layer that owns all SQL and transactions."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def paper_exists(self, file_hash: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM papers WHERE file_hash = ?", (file_hash,)
            ).fetchone()
        return row is not None

    def add_paper(
        self,
        *,
        file_hash: str,
        filename: str,
        filepath: str,
        metadata: ExtractedMetadata,
        classification: ClassificationResult | None,
        classification_error: str | None = None,
        processing_seconds: float | None = None,
    ) -> int:
        """Insert a paper and both immutable AI and editable current labels."""

        category = classification.primary_category.value if classification else None
        relevance = classification.relevance.value if classification else None
        reason = classification.relevance_reason if classification else None
        confidence = classification.relevance_confidence if classification else None
        try:
            with self.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO papers (
                        file_hash, filename, filepath, title, authors_json, year, venue,
                        abstract, keywords_json, metadata_sources_json,
                        ai_primary_category, primary_category, ai_relevance, relevance,
                        ai_relevance_reason, relevance_reason,
                        ai_relevance_confidence, relevance_confidence,
                        classification_error, processing_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_hash,
                        filename,
                        filepath,
                        metadata.title,
                        json.dumps(metadata.authors, ensure_ascii=False),
                        metadata.year,
                        metadata.venue,
                        metadata.abstract,
                        json.dumps(metadata.keywords, ensure_ascii=False),
                        json.dumps(metadata.metadata_sources, ensure_ascii=False),
                        category,
                        category,
                        relevance,
                        relevance,
                        reason,
                        reason,
                        confidence,
                        confidence,
                        classification_error,
                        processing_seconds,
                    ),
                )
                paper_id = int(cursor.lastrowid)
                if classification:
                    for source in ("ai", "current"):
                        self._replace_labels(
                            connection, paper_id, "tags", classification.tags, source
                        )
                        self._replace_labels(
                            connection,
                            paper_id,
                            "research_methods",
                            classification.research_methods,
                            source,
                        )
                        self._replace_labels(
                            connection,
                            paper_id,
                            "target_vulnerabilities",
                            classification.target_vulnerabilities,
                            source,
                        )
                return paper_id
        except sqlite3.IntegrityError as exc:
            if "file_hash" in str(exc):
                raise DuplicatePaperError("This PDF has already been registered") from exc
            raise

    def get_paper(self, paper_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            return self._hydrate(connection, row) if row else None

    def search_papers(
        self,
        *,
        keyword: str = "",
        categories: Sequence[str] = (),
        tags: Sequence[str] = (),
        methods: Sequence[str] = (),
        vulnerabilities: Sequence[str] = (),
        relevances: Sequence[str] = (),
        statuses: Sequence[str] = (),
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["1 = 1"]
        parameters: list[Any] = []

        if keyword.strip():
            pattern = f"%{keyword.strip().casefold()}%"
            clauses.append(
                """(
                    lower(COALESCE(p.title, '')) LIKE ?
                    OR lower(COALESCE(p.abstract, '')) LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM paper_tags pt JOIN tags t ON t.id = pt.tag_id
                        WHERE pt.paper_id = p.id AND pt.value_source = 'current'
                          AND lower(t.name) LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM paper_vulnerabilities pv
                        JOIN vulnerabilities v ON v.id = pv.vulnerability_id
                        WHERE pv.paper_id = p.id AND pv.value_source = 'current'
                          AND lower(v.name) LIKE ?
                    )
                )"""
            )
            parameters.extend([pattern] * 4)

        self._add_in_filter(clauses, parameters, "p.primary_category", categories)
        self._add_in_filter(clauses, parameters, "p.relevance", relevances)
        self._add_in_filter(clauses, parameters, "p.status", statuses)
        self._add_label_filter(clauses, parameters, "tags", tags)
        self._add_label_filter(clauses, parameters, "research_methods", methods)
        self._add_label_filter(
            clauses, parameters, "target_vulnerabilities", vulnerabilities
        )
        if year_min is not None:
            clauses.append("p.year >= ?")
            parameters.append(year_min)
        if year_max is not None:
            clauses.append("p.year <= ?")
            parameters.append(year_max)

        sql = f"""
            SELECT p.* FROM papers p
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE p.relevance WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
                     p.year DESC, lower(COALESCE(p.title, p.filename))
        """
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
            return [self._hydrate(connection, row) for row in rows]

    def update_review(
        self,
        paper_id: int,
        *,
        primary_category: str,
        tags: Sequence[str],
        relevance: str,
        status: str,
        research_methods: Sequence[str] | None = None,
        target_vulnerabilities: Sequence[str] | None = None,
        relevance_reason: str | None = None,
    ) -> None:
        """Update editable values while retaining the original AI result."""

        category = PrimaryCategory(primary_category).value
        relevance_value = Relevance(relevance).value
        status_value = PaperStatus(status).value
        normalized_reason = (
            " ".join(relevance_reason.split())[:500] if relevance_reason else None
        )
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE papers
                SET primary_category = ?, relevance = ?,
                    relevance_reason = COALESCE(?, relevance_reason), status = ?,
                    manually_reviewed = 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    category,
                    relevance_value,
                    normalized_reason,
                    status_value,
                    paper_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Paper {paper_id} does not exist")
            self._replace_labels(connection, paper_id, "tags", tags, "current")
            if research_methods is not None:
                self._replace_labels(
                    connection,
                    paper_id,
                    "research_methods",
                    research_methods,
                    "current",
                )
            if target_vulnerabilities is not None:
                self._replace_labels(
                    connection,
                    paper_id,
                    "target_vulnerabilities",
                    target_vulnerabilities,
                    "current",
                )

    def dashboard_counts(self) -> dict[str, Any]:
        with self.connect() as connection:
            total = connection.execute("SELECT count(*) FROM papers").fetchone()[0]
            unread = connection.execute(
                "SELECT count(*) FROM papers WHERE status = 'Unread'"
            ).fetchone()[0]
            category_rows = connection.execute(
                """SELECT COALESCE(primary_category, 'Unclassified') AS label, count(*) AS count
                   FROM papers GROUP BY primary_category ORDER BY count DESC"""
            ).fetchall()
            relevance_rows = connection.execute(
                """SELECT COALESCE(relevance, 'Unclassified') AS label, count(*) AS count
                   FROM papers GROUP BY relevance ORDER BY label"""
            ).fetchall()
        return {
            "total": total,
            "unread": unread,
            "categories": {row["label"]: row["count"] for row in category_rows},
            "relevances": {row["label"]: row["count"] for row in relevance_rows},
        }

    def list_facets(self) -> dict[str, list[str]]:
        with self.connect() as connection:
            return {
                key: [
                    row[0]
                    for row in connection.execute(
                        f"""SELECT DISTINCT l.name
                            FROM {table} l JOIN {junction} j ON j.{foreign_key} = l.id
                            WHERE j.value_source = 'current'
                            ORDER BY lower(l.name)"""
                    ).fetchall()
                ]
                for key, (table, junction, foreign_key) in LABEL_TABLES.items()
            }

    @staticmethod
    def _add_in_filter(
        clauses: list[str],
        parameters: list[Any],
        column: str,
        values: Sequence[str],
    ) -> None:
        if values:
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"{column} IN ({placeholders})")
            parameters.extend(values)

    @staticmethod
    def _add_label_filter(
        clauses: list[str],
        parameters: list[Any],
        key: str,
        values: Sequence[str],
    ) -> None:
        if not values:
            return
        table, junction, foreign_key = LABEL_TABLES[key]
        placeholders = ", ".join("?" for _ in values)
        clauses.append(
            f"""EXISTS (
                SELECT 1 FROM {junction} j JOIN {table} l ON l.id = j.{foreign_key}
                WHERE j.paper_id = p.id AND j.value_source = 'current'
                  AND l.name IN ({placeholders})
            )"""
        )
        parameters.extend(values)

    def _replace_labels(
        self,
        connection: sqlite3.Connection,
        paper_id: int,
        key: str,
        labels: Iterable[str],
        source: str,
    ) -> None:
        table, junction, foreign_key = LABEL_TABLES[key]
        connection.execute(
            f"DELETE FROM {junction} WHERE paper_id = ? AND value_source = ?",
            (paper_id, source),
        )
        seen: set[str] = set()
        for label in labels:
            cleaned = " ".join(str(label).split())[:120]
            normalized = cleaned.casefold()
            if not cleaned or normalized in seen:
                continue
            seen.add(normalized)
            connection.execute(f"INSERT OR IGNORE INTO {table} (name) VALUES (?)", (cleaned,))
            label_row = connection.execute(
                f"SELECT id FROM {table} WHERE name = ? COLLATE NOCASE", (cleaned,)
            ).fetchone()
            connection.execute(
                f"INSERT INTO {junction} (paper_id, {foreign_key}, value_source) VALUES (?, ?, ?)",
                (paper_id, label_row[0], source),
            )

    def _hydrate(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        paper = dict(row)
        paper["authors"] = json.loads(paper.pop("authors_json"))
        paper["keywords"] = json.loads(paper.pop("keywords_json"))
        paper["metadata_sources"] = json.loads(paper.pop("metadata_sources_json"))
        for key in LABEL_TABLES:
            paper[key] = self._get_labels(connection, paper["id"], key, "current")
            paper[f"ai_{key}"] = self._get_labels(connection, paper["id"], key, "ai")
        paper["manually_reviewed"] = bool(paper["manually_reviewed"])
        return paper

    @staticmethod
    def _get_labels(
        connection: sqlite3.Connection,
        paper_id: int,
        key: str,
        source: str,
    ) -> list[str]:
        table, junction, foreign_key = LABEL_TABLES[key]
        return [
            row[0]
            for row in connection.execute(
                f"""SELECT l.name FROM {table} l
                    JOIN {junction} j ON j.{foreign_key} = l.id
                    WHERE j.paper_id = ? AND j.value_source = ?
                    ORDER BY lower(l.name)""",
                (paper_id, source),
            ).fetchall()
        ]
