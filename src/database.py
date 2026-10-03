"""SQLite persistence with normalized searchable classification labels."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
import json
import hashlib
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from src.models import (
    ClassificationResult,
    ClassificationProvenance,
    ClassificationStatus,
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
    introduction_excerpt TEXT,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    metadata_sources_json TEXT NOT NULL DEFAULT '{}',
    metadata_review_reasons_json TEXT NOT NULL DEFAULT '[]',
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
    classification_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(classification_status IN ('pending', 'classified', 'failed', 'needs_review')),
    classification_error TEXT,
    classification_provider TEXT CHECK(classification_provider IN ('local', 'openai')),
    classification_model TEXT,
    classified_at TEXT,
    processing_seconds REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS classification_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    provider TEXT CHECK(provider IN ('local', 'openai')),
    model TEXT,
    status TEXT NOT NULL CHECK(status IN ('classified', 'failed')),
    result_json TEXT,
    error TEXT,
    classified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_classification_runs_paper ON classification_runs(paper_id);
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

# Fixed identifiers only: controlled refresh never runs migrations or user SQL.
SNAPSHOT_TABLES = (
    "papers", "tags", "research_methods", "vulnerabilities", "paper_tags",
    "paper_methods", "paper_vulnerabilities", "classification_runs", "sqlite_sequence",
)
METADATA_COLUMNS = (
    "title", "authors_json", "year", "venue", "abstract", "introduction_excerpt",
    "keywords_json", "metadata_sources_json", "metadata_review_reasons_json",
)


def snapshot_digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def metadata_values(metadata: ExtractedMetadata) -> tuple[Any, ...]:
    metadata = ExtractedMetadata.model_validate(metadata.model_dump())
    return (
        metadata.title, json.dumps(metadata.authors, ensure_ascii=False), metadata.year,
        metadata.venue, metadata.abstract, metadata.introduction_excerpt,
        json.dumps(metadata.keywords, ensure_ascii=False),
        json.dumps(metadata.metadata_sources, ensure_ascii=False),
        json.dumps(metadata.review_reasons, ensure_ascii=False),
    )


class DuplicatePaperError(RuntimeError):
    """Raised when a file hash already exists."""


def _validated_processing_seconds(value: float | None) -> float | None:
    """Accept optional, finite, non-negative elapsed seconds at the storage boundary."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("processing_seconds must be a finite non-negative number")
    try:
        seconds = float(value)
    except OverflowError:
        raise ValueError("processing_seconds must be a finite non-negative number") from None
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("processing_seconds must be a finite non-negative number")
    return seconds


class Database:
    """Small repository layer that owns all SQL and transactions."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def require_quiescent(self) -> None:
        if any(Path(str(self.path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("Close database users and clear active SQLite sidecars first")

    @contextmanager
    def connect_readonly(self) -> Iterator[sqlite3.Connection]:
        """Read a quiescent DB without initialization, migration or sidecar creation.

        Immutable mode is safe only for a closed application with no journal/WAL.
        The refresh coordinator additionally checks DB fingerprints before/after.
        """
        if not self.path.is_file():
            raise ValueError("Database must already exist")
        self.require_quiescent()
        connection = sqlite3.connect(self.path.as_uri() + "?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
        """Exact local comparison data, including schema, labels and all history."""
        return {
            "schema": [list(row) for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
            )],
            "tables": {
                table: [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                for table in SNAPSHOT_TABLES
            },
        }

    @staticmethod
    def update_metadata_only(
        connection: sqlite3.Connection, paper_id: int, file_hash: str,
        metadata: ExtractedMetadata,
    ) -> None:
        """Participate in a caller-owned batch transaction; change metadata only."""
        cursor = connection.execute(
            """UPDATE papers SET title = ?, authors_json = ?, year = ?, venue = ?,
               abstract = ?, introduction_excerpt = ?, keywords_json = ?,
               metadata_sources_json = ?, metadata_review_reasons_json = ?,
               updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ? AND file_hash = ?""",
            (*metadata_values(metadata), paper_id, file_hash),
        )
        if cursor.rowcount != 1:
            raise ValueError("Paper identity changed before metadata update")

    @contextmanager
    def connect(self, *, existing_only: bool = False) -> Iterator[sqlite3.Connection]:
        if existing_only:
            if not self.path.is_file():
                raise ValueError("Database must already exist")
            self.require_quiescent()
            # mode=rw also refuses creation if the file disappears after this check.
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
        else:
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
            self._migrate_papers(connection)

    @staticmethod
    def _migrate_papers(connection: sqlite3.Connection) -> None:
        """Add v0.1.1 metadata and classification state to existing databases."""

        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(papers)").fetchall()
        }
        additions = {
            "introduction_excerpt": "TEXT",
            "metadata_review_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
            "classification_status": "TEXT NOT NULL DEFAULT 'pending'",
            "manually_reviewed": "INTEGER NOT NULL DEFAULT 0",
            "classification_provider": "TEXT CHECK(classification_provider IN ('local', 'openai'))",
            "classification_model": "TEXT",
            "classified_at": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE papers ADD COLUMN {name} {declaration}")
        connection.execute(
            """UPDATE papers SET classification_status = 'classified'
               WHERE classification_status = 'pending' AND ai_primary_category IS NOT NULL"""
        )
        connection.execute(
            """UPDATE papers SET classification_status = 'failed'
               WHERE classification_status = 'pending'
                 AND classification_error IS NOT NULL
                 AND classification_error NOT LIKE '%not configured%'"""
        )
        # Earlier builds projected untouched AI values into editable fields. Those
        # rows were not reviewed, so retain their ai_* values and clear the projection.
        editable_columns = [
            name
            for name in (
                "primary_category",
                "relevance",
                "relevance_reason",
                "relevance_confidence",
            )
            if name in columns or name in additions
        ]
        if editable_columns:
            assignments = ", ".join(f"{name} = NULL" for name in editable_columns)
            # SQLite can dirty pages even when an UPDATE assigns the same NULLs.
            needs_cleanup = " OR ".join(f"{name} IS NOT NULL" for name in editable_columns)
            connection.execute(
                f"""UPDATE papers SET {assignments} WHERE manually_reviewed = 0
                    AND ({needs_cleanup})"""
            )
        for _, junction, _ in LABEL_TABLES.values():
            connection.execute(
                f"""DELETE FROM {junction} WHERE value_source = 'current'
                    AND paper_id IN (SELECT id FROM papers WHERE manually_reviewed = 0)"""
            )
        # Preserve pre-provider AI originals without inventing their provenance/date.
        for row in connection.execute(
            """SELECT * FROM papers p WHERE ai_primary_category IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM classification_runs r WHERE r.paper_id = p.id)"""
        ).fetchall():
            paper = dict(row)
            snapshot = {
                key: paper.get(f"ai_{key}") for key in (
                    "primary_category", "relevance", "relevance_reason", "relevance_confidence"
                )
            }
            for key in LABEL_TABLES:
                snapshot[key] = Database._get_labels(connection, paper["id"], key, "ai")
            connection.execute(
                """INSERT INTO classification_runs
                   (paper_id, provider, model, status, result_json, classified_at)
                   VALUES (?, ?, ?, 'classified', ?, ?)""",
                (paper["id"], paper.get("classification_provider"), paper.get("classification_model"),
                 json.dumps(snapshot, ensure_ascii=False), paper.get("classified_at")),
            )

    def paper_exists(self, file_hash: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM papers WHERE file_hash = ?", (file_hash,)
            ).fetchone()
        return row is not None

    def get_paper_by_hash(self, file_hash: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM papers WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            return self._hydrate(connection, row) if row else None

    def add_paper(
        self,
        *,
        file_hash: str,
        filename: str,
        filepath: str,
        metadata: ExtractedMetadata,
        classification: ClassificationResult | None,
        classification_error: str | None = None,
        classification_status: ClassificationStatus | str | None = None,
        processing_seconds: float | None = None,
        classification_provider: str | None = None,
        classification_model: str | None = None,
    ) -> int:
        """Insert AI output while leaving human-reviewed values unset."""

        processing_seconds = _validated_processing_seconds(processing_seconds)
        provenance = ClassificationProvenance(provider=classification_provider, model=classification_model)
        if classification is not None:
            classification = ClassificationResult.model_validate(classification)
        category = classification.primary_category.value if classification else None
        relevance = classification.relevance.value if classification else None
        reason = classification.relevance_reason if classification else None
        confidence = classification.relevance_confidence if classification else None
        status = ClassificationStatus(
            classification_status
            or (
                ClassificationStatus.CLASSIFIED
                if classification
                else (
                    ClassificationStatus.NEEDS_REVIEW
                    if metadata.review_reasons
                    else ClassificationStatus.PENDING
                )
            )
        ).value
        try:
            with self.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO papers (
                        file_hash, filename, filepath, title, authors_json, year, venue,
                        abstract, introduction_excerpt, keywords_json, metadata_sources_json,
                        metadata_review_reasons_json, classification_status,
                        ai_primary_category, primary_category, ai_relevance, relevance,
                        ai_relevance_reason, relevance_reason,
                        ai_relevance_confidence, relevance_confidence,
                        classification_error, processing_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        metadata.introduction_excerpt,
                        json.dumps(metadata.keywords, ensure_ascii=False),
                        json.dumps(metadata.metadata_sources, ensure_ascii=False),
                        json.dumps(metadata.review_reasons, ensure_ascii=False),
                        status,
                        category,
                        None,
                        relevance,
                        None,
                        reason,
                        None,
                        confidence,
                        None,
                        classification_error,
                        processing_seconds,
                    ),
                )
                paper_id = int(cursor.lastrowid)
                if classification:
                    self._replace_labels(
                        connection, paper_id, "tags", classification.tags, "ai"
                    )
                    self._replace_labels(
                        connection,
                        paper_id,
                        "research_methods",
                        classification.research_methods,
                        "ai",
                    )
                    self._replace_labels(
                        connection,
                        paper_id,
                        "target_vulnerabilities",
                        classification.target_vulnerabilities,
                        "ai",
                    )
                self._record_classification(
                    connection, paper_id, classification, status, classification_error, provenance
                )
                return paper_id
        except sqlite3.IntegrityError as exc:
            if "file_hash" in str(exc):
                raise DuplicatePaperError("This PDF has already been registered") from exc
            raise

    def update_metadata(
        self,
        paper_id: int,
        metadata: ExtractedMetadata,
        *,
        classification_status: ClassificationStatus | str,
        classification_error: str | None = None,
    ) -> None:
        status = ClassificationStatus(classification_status).value
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE papers SET title = ?, authors_json = ?, year = ?, venue = ?,
                   abstract = ?, introduction_excerpt = ?, keywords_json = ?,
                   metadata_sources_json = ?, metadata_review_reasons_json = ?,
                   classification_status = ?, classification_error = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                (
                    metadata.title,
                    json.dumps(metadata.authors, ensure_ascii=False),
                    metadata.year,
                    metadata.venue,
                    metadata.abstract,
                    metadata.introduction_excerpt,
                    json.dumps(metadata.keywords, ensure_ascii=False),
                    json.dumps(metadata.metadata_sources, ensure_ascii=False),
                    json.dumps(metadata.review_reasons, ensure_ascii=False),
                    status,
                    classification_error,
                    paper_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Paper {paper_id} does not exist")

    def update_classification(
        self,
        paper_id: int,
        classification: ClassificationResult | None,
        *,
        classification_status: ClassificationStatus | str,
        classification_error: str | None = None,
        classification_provider: str | None = None,
        classification_model: str | None = None,
        processing_seconds: float | None = None,
    ) -> None:
        """Save a retry result and its duration; omitted duration preserves the old value."""

        processing_seconds = _validated_processing_seconds(processing_seconds)
        status = ClassificationStatus(classification_status).value
        provenance = ClassificationProvenance(provider=classification_provider, model=classification_model)
        if classification is not None:
            classification = ClassificationResult.model_validate(classification)
        with self.connect() as connection:
            self.write_classification(
                connection, paper_id, classification, status=status,
                error=classification_error, provenance=provenance,
                processing_seconds=processing_seconds,
            )

    def write_classification(
        self, connection: sqlite3.Connection, paper_id: int,
        classification: ClassificationResult | None, *, status: str,
        error: str | None, provenance: ClassificationProvenance,
        processing_seconds: float | None,
    ) -> None:
        """Append a validated attempt inside an existing transaction."""
        status = ClassificationStatus(status).value
        provenance = ClassificationProvenance.model_validate(provenance)
        processing_seconds = _validated_processing_seconds(processing_seconds)
        if classification is not None:
            classification = ClassificationResult.model_validate(classification)
        classification_error = error
        row = connection.execute(
            "SELECT manually_reviewed FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Paper {paper_id} does not exist")
        self._record_classification(
            connection, paper_id, classification, status, classification_error, provenance
        )
        if classification is None:
            connection.execute(
                """UPDATE papers SET classification_status = ?, classification_error = ?,
                   processing_seconds = COALESCE(?, processing_seconds),
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
                (status, classification_error, processing_seconds, paper_id),
            )
            return

        category = classification.primary_category.value
        relevance = classification.relevance.value
        reason = classification.relevance_reason
        confidence = classification.relevance_confidence
        connection.execute(
            """UPDATE papers SET ai_primary_category = ?, ai_relevance = ?,
               ai_relevance_reason = ?, ai_relevance_confidence = ?,
               classification_status = ?, classification_error = NULL,
               processing_seconds = COALESCE(?, processing_seconds),
               updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?""",
            (category, relevance, reason, confidence, status, processing_seconds, paper_id),
        )
        self._replace_labels(connection, paper_id, "tags", classification.tags, "ai")
        self._replace_labels(
            connection, paper_id, "research_methods", classification.research_methods, "ai"
        )
        self._replace_labels(
            connection,
            paper_id,
            "target_vulnerabilities",
            classification.target_vulnerabilities,
            "ai",
        )
        # A retry replaces AI-owned values only. It never seeds or overwrites
        # the human-owned current values, regardless of review status.

    @staticmethod
    def _record_classification(
        connection: sqlite3.Connection, paper_id: int,
        classification: ClassificationResult | None, status: str,
        error: str | None, provenance: ClassificationProvenance,
    ) -> None:
        """Append attempts; latest successful provenance belongs to ai_* fields."""
        if classification is None and status != ClassificationStatus.FAILED.value:
            return
        timestamp = connection.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        ).fetchone()[0] if classification else None
        connection.execute(
            """INSERT INTO classification_runs
               (paper_id, provider, model, status, result_json, error, classified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, provenance.provider, provenance.model,
             'classified' if classification else 'failed',
             classification.model_dump_json() if classification else None,
             None if classification else error, timestamp),
        )
        if classification:
            connection.execute(
                """UPDATE papers SET classification_provider = ?, classification_model = ?,
                   classified_at = ? WHERE id = ?""",
                (provenance.provider, provenance.model, timestamp, paper_id),
            )

    def classification_history(self, paper_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM classification_runs WHERE paper_id = ? ORDER BY id", (paper_id,)
            ).fetchall()
        history = []
        for row in rows:
            item = dict(row)
            result_json = item.pop("result_json")
            item["result"] = json.loads(result_json) if result_json else None
            history.append(item)
        return history

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
        classification_statuses: Sequence[str] = (),
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
                        WHERE pt.paper_id = p.id
                          AND pt.value_source = CASE WHEN p.manually_reviewed = 1
                              THEN 'current' ELSE 'ai' END
                          AND lower(t.name) LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM paper_vulnerabilities pv
                        JOIN vulnerabilities v ON v.id = pv.vulnerability_id
                        WHERE pv.paper_id = p.id
                          AND pv.value_source = CASE WHEN p.manually_reviewed = 1
                              THEN 'current' ELSE 'ai' END
                          AND lower(v.name) LIKE ?
                    )
                )"""
            )
            parameters.extend([pattern] * 4)

        self._add_in_filter(
            clauses,
            parameters,
            "CASE WHEN p.manually_reviewed = 1 THEN p.primary_category ELSE p.ai_primary_category END",
            categories,
        )
        self._add_in_filter(
            clauses,
            parameters,
            "CASE WHEN p.manually_reviewed = 1 THEN p.relevance ELSE p.ai_relevance END",
            relevances,
        )
        self._add_in_filter(clauses, parameters, "p.status", statuses)
        self._add_in_filter(
            clauses, parameters, "p.classification_status", classification_statuses
        )
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
            ORDER BY CASE
                         CASE WHEN p.manually_reviewed = 1 THEN p.relevance ELSE p.ai_relevance END
                         WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
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
                """SELECT COALESCE(
                       CASE WHEN manually_reviewed = 1 THEN primary_category
                            ELSE ai_primary_category END, 'Unclassified') AS label,
                       count(*) AS count
                   FROM papers
                   GROUP BY CASE WHEN manually_reviewed = 1 THEN primary_category
                                 ELSE ai_primary_category END
                   ORDER BY count DESC"""
            ).fetchall()
            relevance_rows = connection.execute(
                """SELECT COALESCE(
                       CASE WHEN manually_reviewed = 1 THEN relevance ELSE ai_relevance END,
                       'Unclassified') AS label,
                       count(*) AS count
                   FROM papers
                   GROUP BY CASE WHEN manually_reviewed = 1 THEN relevance ELSE ai_relevance END
                   ORDER BY label"""
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
                            JOIN papers p ON p.id = j.paper_id
                            WHERE j.value_source = CASE WHEN p.manually_reviewed = 1
                                THEN 'current' ELSE 'ai' END
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
                WHERE j.paper_id = p.id
                  AND j.value_source = CASE WHEN p.manually_reviewed = 1 THEN 'current' ELSE 'ai' END
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
        paper["metadata_review_reasons"] = json.loads(
            paper.pop("metadata_review_reasons_json", "[]")
        )
        for key in LABEL_TABLES:
            paper[key] = self._get_labels(connection, paper["id"], key, "current")
            paper[f"ai_{key}"] = self._get_labels(connection, paper["id"], key, "ai")
        paper["manually_reviewed"] = bool(paper["manually_reviewed"])
        paper["effective_primary_category"] = (
            paper["primary_category"]
            if paper["manually_reviewed"]
            else paper["ai_primary_category"]
        )
        paper["effective_relevance"] = (
            paper["relevance"] if paper["manually_reviewed"] else paper["ai_relevance"]
        )
        paper["effective_relevance_reason"] = (
            paper["relevance_reason"]
            if paper["manually_reviewed"]
            else paper["ai_relevance_reason"]
        )
        paper["effective_relevance_confidence"] = (
            paper["relevance_confidence"]
            if paper["manually_reviewed"]
            else paper["ai_relevance_confidence"]
        )
        for key in LABEL_TABLES:
            paper[f"effective_{key}"] = (
                paper[key] if paper["manually_reviewed"] else paper[f"ai_{key}"]
            )
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
