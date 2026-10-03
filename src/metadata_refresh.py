"""Controlled metadata refresh and targeted retries, separate from normal scans."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.classifier import ClassifierProvider
from src.database import Database, METADATA_COLUMNS, snapshot_digest
from src.metadata_extractor import classification_input_issues, extract_metadata
from src.models import ClassificationProvenance, ClassificationResult, ExtractedMetadata
from src.pdf_parser import has_pdf_signature, is_within_directory, parse_pdf, sha256_file


INPUT_FIELDS = ("title", "abstract", "keywords", "introduction_excerpt")
METADATA_FIELDS = (
    "title", "authors", "year", "venue", "abstract", "introduction_excerpt",
    "keywords", "metadata_sources", "review_reasons",
)
PHASE_A_IDS = (14, 15, 19, 21, 22, 23, 26, 27, 30, 34, 35, 39)


class RefreshRejected(ValueError):
    """A fixed, content-free preflight or concurrency diagnostic."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FileStamp(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    mtime_ns: int


class RefreshPaper(StrictModel):
    paper_id: int = Field(gt=0)
    filename: str
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    old_metadata: dict[str, Any]
    new_metadata: ExtractedMetadata
    input_issues: list[str]

    @property
    def changes(self) -> list[str]:
        new = self.new_metadata.model_dump()
        return [key for key in METADATA_FIELDS if self.old_metadata[key] != new[key]]

    @property
    def input_changed(self) -> bool:
        return bool(set(self.changes).intersection(INPUT_FIELDS))


class RefreshPlan(StrictModel):
    version: Literal[1] = 1
    expected_count: int = Field(gt=0)
    expected_input_ids: list[int] | None
    database_stamp: FileStamp
    database_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pdf_manifest: dict[str, FileStamp]
    papers: list[RefreshPaper]
    errors: list[str]
    audit_evidence: dict[str, Any] = Field(default_factory=dict)
    frozen_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    format_only_ids: list[int] = Field(default_factory=list)

    @property
    def target_ids(self) -> list[int]:
        return [paper.paper_id for paper in self.papers if paper.input_changed]

    @property
    def reclassification_ids(self) -> list[int]:
        return [paper_id for paper_id in self.target_ids if paper_id not in self.format_only_ids]

    @property
    def digest(self) -> str:
        return snapshot_digest(self.model_dump(mode="json"))

    def require_applicable(self) -> None:
        if self.errors or any(p.input_issues for p in self.papers):
            raise RefreshRejected("Preflight rejected; inspect the dry-run report")


class ApplyReceipt(StrictModel):
    version: Literal[1] = 1
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backup_filename: str
    target_ids: list[int]


def file_stamp(path: Path) -> FileStamp:
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RefreshRejected("File changed while reading")
    return FileStamp(sha256=digest, size=after.st_size, mtime_ns=after.st_mtime_ns)


def read_baseline(database: Database) -> tuple[FileStamp, dict[str, Any]]:
    """No writable connection, initialize(), migrations, logger or provider."""
    before = file_stamp(database.path)
    with database.connect_readonly() as connection:
        snapshot = database.snapshot(connection)
    database.require_quiescent()
    if before != file_stamp(database.path):
        raise RefreshRejected("Database changed while reading")
    return before, snapshot


def row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": row["title"], "authors": json.loads(row["authors_json"]),
        "year": row["year"], "venue": row["venue"], "abstract": row["abstract"],
        "introduction_excerpt": row["introduction_excerpt"],
        "keywords": json.loads(row["keywords_json"]),
        "metadata_sources": json.loads(row["metadata_sources_json"]),
        "review_reasons": json.loads(row["metadata_review_reasons_json"]),
    }


def inventory(inbox: Path) -> tuple[dict[str, FileStamp], dict[str, Path], list[str]]:
    """Inspect every PDF suffix, including invalid PDFs ordinary discovery skips."""
    manifest: dict[str, FileStamp] = {}
    hashes: dict[str, Path] = {}
    errors: list[str] = []
    if not inbox.is_dir():
        return manifest, hashes, ["Missing inbox directory"]
    for path in sorted(inbox.rglob("*")):
        if path.suffix.casefold() != ".pdf":
            continue
        if not is_within_directory(path, inbox) or not has_pdf_signature(path):
            errors.append("Invalid or uncontained PDF candidate")
            continue
        stamp = file_stamp(path)
        manifest[path.relative_to(inbox).as_posix()] = stamp
        if stamp.sha256 in hashes:
            errors.append("Duplicate PDF hash")
        hashes[stamp.sha256] = path
    return manifest, hashes, errors


def build_plan(
    database: Database, inbox: Path, *, expected_count: int = 40,
    expected_input_ids: list[int] | None = None, audit_dir: Path | None = None,
) -> tuple[RefreshPlan, dict[str, Any]]:
    stamp, snapshot = read_baseline(database)
    rows = snapshot["tables"]["papers"]
    manifest, paths, errors = inventory(inbox)
    initial_inventory_errors = list(errors)
    if len(rows) != expected_count:
        errors.append("Database paper count differs from expected count")
    if len(manifest) != expected_count:
        errors.append("Inbox PDF count differs from expected count")
    db_hashes = [row["file_hash"] for row in rows]
    if len(set(db_hashes)) != len(db_hashes):
        errors.append("Duplicate database hash")
    if any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in db_hashes):
        raise RefreshRejected("Invalid database file hash")
    if set(db_hashes) - paths.keys():
        errors.append("Missing PDF or hash mismatch for registered paper")
    if paths.keys() - set(db_hashes):
        errors.append("Unexpected PDF without matching database hash")
    papers = []
    for row in rows:
        path = paths.get(row["file_hash"])
        if path is None:
            continue
        if Path(row["filename"]).name != row["filename"] or any(c in row["filename"] for c in "\\/\r\n"):
            raise RefreshRejected("Invalid database filename")
        try:
            metadata = extract_metadata(parse_pdf(path, inbox), path.name)
            metadata = ExtractedMetadata.model_validate(metadata.model_dump())
            issues = list(dict.fromkeys(metadata.review_reasons + classification_input_issues(
                title=metadata.title, abstract=metadata.abstract,
                introduction_excerpt=metadata.introduction_excerpt,
            )))
            old = row_metadata(row)
            ExtractedMetadata.model_validate(old)
            papers.append(RefreshPaper(
                paper_id=row["id"], filename=row["filename"], file_hash=row["file_hash"],
                old_metadata=old, new_metadata=metadata, input_issues=issues,
            ))
        except Exception as exc:
            errors.append(f"Paper {row['id']}: extraction failed ({type(exc).__name__})")
    actual_ids = sorted(p.paper_id for p in papers if p.input_changed)
    if expected_input_ids is not None and actual_ids != sorted(expected_input_ids):
        errors.append("Classification input target set differs from expected IDs")
    database.require_quiescent()
    final_manifest, _, final_errors = inventory(inbox)
    if file_stamp(database.path) != stamp or final_manifest != manifest or final_errors != initial_inventory_errors:
        errors.append("Database or PDF inventory changed during preflight")
    plan = RefreshPlan(
        expected_count=expected_count, expected_input_ids=expected_input_ids,
        database_stamp=stamp, database_snapshot_sha256=snapshot_digest(snapshot),
        pdf_manifest=manifest, papers=papers, errors=errors,
    )
    if audit_dir is not None:
        verify_phase_evidence(plan, audit_dir)
    return plan, baseline_report(stamp, snapshot, manifest)


def verify_phase_evidence(plan: RefreshPlan, audit_dir: Path) -> None:
    """Cross-check audit identities, original inputs, Phase A and Phase B outputs."""
    try:
        names = ("phase-a-report.md", "phase-a-final.json", "phase-b-final.json", "phase-a-protected.json")
        documents = {name: (audit_dir / name).read_text(encoding="utf-8") for name in names}
        report_ids = sorted(int(n) for n in re.findall(r"^### ID (\d+)\b", documents[names[0]], re.M))
        a_rows, b_rows = json.loads(documents[names[1]]), json.loads(documents[names[2]])
        a = {row["id"]: row for row in a_rows}
        b = {row["id"]: row for row in b_rows}
        protected = json.loads(documents[names[3]])
        if not report_ids or len(report_ids) != len(set(report_ids)):
            raise ValueError
        if (set(a) != set(b) or set(a) != {p.paper_id for p in plan.papers}
                or len(a) != 40 or len(a_rows) != 40 or len(b_rows) != 40):
            raise ValueError
        for paper in plan.papers:
            ar, br = a[paper.paper_id], b[paper.paper_id]
            stamps = [value for name, value in protected.items()
                      if Path(name.replace("\\", "/")).name == paper.filename]
            if len(stamps) != 1 or stamps[0]["sha256"] != paper.file_hash:
                raise ValueError
            if ar["filename"] != paper.filename or br["filename"] != paper.filename:
                raise ValueError
            for key in INPUT_FIELDS:
                if (paper.old_metadata[key] != ar["old"][key]
                        or ar["new"][key] != br["old"][key]
                        or ar["new"][key] != br["new"][key]
                        or paper.new_metadata.model_dump()[key] != br["new"][key]):
                    raise ValueError
        actual_ids = sorted(row["id"] for row in a_rows
                            if any(row["old"][key] != row["new"][key] for key in INPUT_FIELDS))
        if actual_ids != plan.target_ids or not set(report_ids).issubset(actual_ids):
            raise ValueError
        plan.audit_evidence = {
            "phase_a_target_ids": report_ids, "phase_b_input_fields_equal": 160,
            "phase_a_actual_input_changed_ids": actual_ids,
            "phase_a_additional_input_changed_ids": sorted(set(actual_ids) - set(report_ids)),
            "current_input_fields_equal_to_phase_b": 160,
            "files": {name: sha256_file(audit_dir / name) for name in names},
        }
    except Exception:
        plan.errors.append("Phase A / Phase B evidence does not match current hashes and inputs")


def baseline_report(stamp: FileStamp, snapshot: dict[str, Any], manifest: dict[str, FileStamp]) -> dict[str, Any]:
    # Local evidence contains all stored values and runs, but never absolute paths.
    tables = {name: [dict(row) for row in rows] for name, rows in snapshot["tables"].items()}
    for paper in tables["papers"]:
        paper.pop("filepath", None)
    rows = tables["papers"]
    labels = {}
    for key, table, junction, foreign_key in (
        ("tags", "tags", "paper_tags", "tag_id"),
        ("methods", "research_methods", "paper_methods", "method_id"),
        ("vulnerabilities", "vulnerabilities", "paper_vulnerabilities", "vulnerability_id"),
    ):
        definitions = {r["id"]: r["name"] for r in tables[table]}
        for paper in rows:
            values = labels.setdefault(str(paper["id"]), {})
            for source in ("ai", "current"):
                values[f"{source}_{key}"] = [definitions[r[foreign_key]] for r in tables[junction]
                                            if r["paper_id"] == paper["id"] and r["value_source"] == source]
    return {
        "database": stamp.model_dump(), "snapshot_sha256": snapshot_digest(snapshot),
        "paper_count": len(rows), "paper_ids": [p["id"] for p in rows],
        "classification_status_counts": dict(Counter(p["classification_status"] for p in rows)),
        "manually_reviewed_count": sum(p["manually_reviewed"] for p in rows),
        "classification_runs_count": len(tables["classification_runs"]),
        "paper_labels": labels,
        "pdf_manifest": {name: value.model_dump() for name, value in manifest.items()},
        "tables": tables,
    }


def summary(plan: RefreshPlan) -> dict[str, Any]:
    return {
        "expected_paper_count": plan.expected_count,
        "expected_input_ids": plan.expected_input_ids,
        "paper_count": len(plan.papers), "pdf_count": len(plan.pdf_manifest),
        "hash_matches": len(plan.papers), "metadata_refresh_targets": len(plan.papers),
        "metadata_changed": sum(bool(p.changes) for p in plan.papers),
        "bibliographic_only_changed": sum(bool(p.changes) and not p.input_changed for p in plan.papers),
        "classification_input_changed": len(plan.target_ids), "target_ids": plan.target_ids,
        "reclassification_ids": plan.reclassification_ids,
        "reclassification_count": len(plan.reclassification_ids),
        "format_only_ids": plan.format_only_ids,
        "frozen_manifest_sha256": plan.frozen_manifest_sha256,
        "production_write_manifest_required": plan.frozen_manifest_sha256 is None,
        "production_write_ready": bool(plan.frozen_manifest_sha256) and not plan.errors
                                  and not any(p.input_issues for p in plan.papers),
        "classification_input_issues": sum(bool(p.input_issues) for p in plan.papers),
        "human_current_changes": 0, "classification_history_changes": 0,
        "apply_allowed": not plan.errors and not any(p.input_issues for p in plan.papers),
        "errors": plan.errors, "audit_evidence": plan.audit_evidence,
    }


def dry_run_report(plan: RefreshPlan) -> str:
    lines = ["# Controlled metadata refresh — dry-run", "", "```json",
             json.dumps(summary(plan), ensure_ascii=False, indent=2), "```", "",
             "|ID|Filename|Hash prefix|Metadata|Title|Authors|Year|Venue|Abstract|Keywords|Introduction|Input changed|Review reasons / input issues|",
             "|---:|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in plan.papers:
        flags = ["yes" if field in p.changes else "no" for field in
                 ("title", "authors", "year", "venue", "abstract", "keywords", "introduction_excerpt")]
        filename = json.dumps(p.filename, ensure_ascii=False).replace("|", "\\|")
        issues = json.dumps(p.input_issues, ensure_ascii=False).replace("|", "\\|")
        lines.append("|" + "|".join([str(p.paper_id), filename, p.file_hash[:12],
                                     "yes" if p.changes else "no", *flags,
                                     "yes" if p.input_changed else "no", issues]) + "|")
    return "\n".join(lines) + "\n"


def unique_name(prefix: str, suffix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:12]}{suffix}"


def backup_database(database: Database, backup_dir: Path, expected: FileStamp, inbox: Path) -> Path:
    """Exclusive byte-exact backup while caller holds BEGIN IMMEDIATE; no WAL."""
    if backup_dir.resolve().is_relative_to(inbox.resolve()):
        raise RefreshRejected("Backup directory must be outside the inbox")
    database.require_quiescent()
    if file_stamp(database.path) != expected:
        raise RefreshRejected("Database changed before backup")
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / unique_name("papers", ".db.bak")
    with database.path.open("rb") as source, path.open("xb") as destination:
        shutil.copyfileobj(source, destination)
        destination.flush()
        os.fsync(destination.fileno())
    if sha256_file(path) != expected.sha256:
        raise RefreshRejected("Backup verification failed; no database writes performed")
    return path


def _assert_snapshot(connection: Any, database: Database, expected_digest: str) -> dict[str, Any]:
    snapshot = database.snapshot(connection)
    if snapshot_digest(snapshot) != expected_digest:
        raise RefreshRejected("Database state changed; create a new dry-run")
    return snapshot


def _assert_inventory(inbox: Path, expected: dict[str, FileStamp]) -> None:
    manifest, _, errors = inventory(inbox)
    if errors or manifest != expected:
        raise RefreshRejected("PDF inventory differs from dry-run or changed during processing")


def _metadata_protected(snapshot: dict[str, Any]) -> dict[str, Any]:
    tables = {name: [dict(r) for r in rows] for name, rows in snapshot["tables"].items()}
    for row in tables["papers"]:
        for key in (*METADATA_COLUMNS, "updated_at"):
            row.pop(key)
    return {"schema": snapshot["schema"], "tables": tables}


def apply_metadata(
    database: Database, inbox: Path, plan: RefreshPlan, *, backup_dir: Path,
    audit_dir: Path | None = None, manifest: Any = None,
) -> ApplyReceipt:
    from src.refresh_manifest import check_binding, bind_manifest
    check_binding(plan, manifest)
    plan.require_applicable()
    # Reparse all inputs before any writable connection or backup; reject stale/tampered plans.
    fresh, _ = build_plan(database, inbox, expected_count=plan.expected_count,
                          expected_input_ids=plan.expected_input_ids, audit_dir=audit_dir)
    fresh.require_applicable()
    if manifest is not None:
        bind_manifest(fresh, manifest)
    if fresh.digest != plan.digest:
        raise RefreshRejected("Dry-run plan is stale or altered")
    with database.connect(existing_only=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        before = _assert_snapshot(connection, database, plan.database_snapshot_sha256)
        _assert_inventory(inbox, plan.pdf_manifest)
        backup = backup_database(database, backup_dir, plan.database_stamp, inbox)
        for paper in plan.papers:
            if paper.changes:
                database.update_metadata_only(connection, paper.paper_id, paper.file_hash, paper.new_metadata)
        after = database.snapshot(connection)
        if _metadata_protected(before) != _metadata_protected(after):
            raise RefreshRejected("Metadata write changed protected values; rolling back")
        by_id = {r["id"]: r for r in after["tables"]["papers"]}
        if any(row_metadata(by_id[p.paper_id]) != p.new_metadata.model_dump() for p in plan.papers):
            raise RefreshRejected("Metadata verification failed; rolling back")
        _assert_inventory(inbox, plan.pdf_manifest)
        receipt = ApplyReceipt(plan_sha256=plan.digest, database_snapshot_sha256=snapshot_digest(after),
                               backup_filename=backup.name, target_ids=plan.reclassification_ids)
    return receipt


def _assert_retry_preservation(before: dict[str, Any], after: dict[str, Any], targets: set[int]) -> None:
    allowed = {"ai_primary_category", "ai_relevance", "ai_relevance_reason", "ai_relevance_confidence",
               "classification_status", "classification_error", "classification_provider",
               "classification_model", "classified_at", "processing_seconds", "updated_at"}
    old_tables, new_tables = before["tables"], after["tables"]
    if before["schema"] != after["schema"]:
        raise RefreshRejected("Classification changed schema; rolling back")
    for old, new in zip(old_tables["papers"], new_tables["papers"], strict=True):
        excluded = allowed if old["id"] in targets else set()
        if {k: v for k, v in old.items() if k not in excluded} != {k: v for k, v in new.items() if k not in excluded}:
            raise RefreshRejected("Classification changed protected paper values; rolling back")
    for table in ("paper_tags", "paper_methods", "paper_vulnerabilities"):
        keep = lambda r: r["paper_id"] not in targets or r["value_source"] == "current"
        if list(filter(keep, old_tables[table])) != list(filter(keep, new_tables[table])):
            raise RefreshRejected("Classification changed protected labels; rolling back")
    for table in ("tags", "research_methods", "vulnerabilities"):
        if new_tables[table][:len(old_tables[table])] != old_tables[table]:
            raise RefreshRejected("Classification changed existing label definitions; rolling back")
    old_runs, new_runs = old_tables["classification_runs"], new_tables["classification_runs"]
    if (new_runs[:len(old_runs)] != old_runs or len(new_runs) != len(old_runs) + len(targets)
            or {r["paper_id"] for r in new_runs[len(old_runs):]} != targets):
        raise RefreshRejected("Classification history verification failed; rolling back")


def reclassify_targets(
    database: Database, inbox: Path, plan: RefreshPlan, receipt: ApplyReceipt, *,
    classifier: ClassifierProvider, backup_dir: Path,
    manifest: Any = None,
) -> dict[str, Any]:
    """Only plan-derived ID/hash pairs, only after metadata apply; append one run each.

    Generate results without a write lock. Commit the batch only if the complete
    receipt-bound DB state is unchanged. A completed receipt cannot be replayed.
    """
    from src.refresh_manifest import check_binding
    check_binding(plan, manifest)
    plan.require_applicable()
    if receipt.plan_sha256 != plan.digest or receipt.target_ids != plan.reclassification_ids:
        raise RefreshRejected("Receipt does not match dry-run plan")
    # Independently bind the old input values to the verified pre-apply backup.
    # A receipt/plan edit cannot expand targets by inventing historical metadata.
    if not re.fullmatch(r"papers-[0-9TZ]+-[0-9a-f]{12}\.db\.bak", receipt.backup_filename):
        raise RefreshRejected("Invalid receipt backup filename")
    old_stamp, original = read_baseline(Database(backup_dir / receipt.backup_filename))
    if old_stamp.sha256 != plan.database_stamp.sha256 or snapshot_digest(original) != plan.database_snapshot_sha256:
        raise RefreshRejected("Original backup does not match dry-run baseline")
    original_rows = {r["id"]: r for r in original["tables"]["papers"]}
    if (len(plan.papers) != plan.expected_count or len(original_rows) != plan.expected_count
            or len({p.paper_id for p in plan.papers}) != plan.expected_count):
        raise RefreshRejected("Plan paper inventory is incomplete or duplicated")
    for paper in plan.papers:
        old = original_rows.get(paper.paper_id)
        if old is None or old["file_hash"] != paper.file_hash or row_metadata(old) != paper.old_metadata:
            raise RefreshRejected("Original metadata does not match verified backup")
    stamp, before = read_baseline(database)
    if snapshot_digest(before) != receipt.database_snapshot_sha256:
        raise RefreshRejected("Applied database state changed or retry already executed")
    _assert_inventory(inbox, plan.pdf_manifest)
    rows = {r["id"]: r for r in before["tables"]["papers"]}
    for p in plan.papers:
        if rows[p.paper_id]["file_hash"] != p.file_hash or row_metadata(rows[p.paper_id]) != p.new_metadata.model_dump():
            raise RefreshRejected("Applied metadata or paper identity does not match plan")
    provenance = ClassificationProvenance(provider=classifier.provider, model=classifier.model)
    attempts = []
    targets = [paper for paper in plan.papers if paper.paper_id in plan.reclassification_ids]
    # Gate the complete target set before the first provider request.
    for paper in targets:
        metadata = paper.new_metadata
        if metadata.review_reasons or classification_input_issues(
            title=metadata.title, abstract=metadata.abstract, introduction_excerpt=metadata.introduction_excerpt,
        ):
            raise RefreshRejected("Target has classification input issues")
    for paper in targets:
        metadata = paper.new_metadata
        started = time.perf_counter()
        try:
            result = ClassificationResult.model_validate(classifier.classify(
                title=metadata.title, abstract=metadata.abstract, keywords=metadata.keywords,
                introduction_excerpt=metadata.introduction_excerpt if not metadata.abstract else None,
            ))
            error = None
        except Exception as exc:
            result = None
            error = f"Targeted classification failed ({type(exc).__name__})"
        attempts.append((paper.paper_id, result, error, time.perf_counter() - started))
    if not attempts:
        return {"classified": 0, "failed": 0, "target_ids": [], "backup_filename": None}
    with database.connect(existing_only=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _assert_snapshot(connection, database, receipt.database_snapshot_sha256)
        _assert_inventory(inbox, plan.pdf_manifest)
        backup = backup_database(database, backup_dir, stamp, inbox)
        for paper_id, result, error, elapsed in attempts:
            database.write_classification(connection, paper_id, result,
                                          status="classified" if result else "failed", error=error,
                                          provenance=provenance, processing_seconds=elapsed)
        _assert_retry_preservation(before, database.snapshot(connection), set(plan.reclassification_ids))
        _assert_inventory(inbox, plan.pdf_manifest)
    return {
        "classified": sum(result is not None for _, result, _, _ in attempts),
        "failed": sum(result is None for _, result, _, _ in attempts),
        "target_ids": plan.reclassification_ids, "backup_filename": backup.name,
    }
