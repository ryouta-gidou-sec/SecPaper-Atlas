"""Local, reviewed observation freeze; no production writes or provider calls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
from typing import Any, Literal

from pydantic import Field

from src.database import snapshot_digest
from src.metadata_refresh import INPUT_FIELDS, RefreshPaper, RefreshPlan, RefreshRejected, StrictModel
from src.pdf_parser import sha256_file


ROOT = Path(__file__).resolve().parents[1]


class AuditDecision(StrictModel):
    paper_id: int = Field(gt=0)
    verdict: Literal["A", "B", "C"]
    phase_a_scope: Literal["primary", "secondary"]
    reason: str = Field(min_length=1)
    source_page: int = Field(gt=0)
    source_evidence: str = Field(min_length=1)


class RefreshManifest(StrictModel):
    version: Literal[1] = 1
    generated_at: str
    observation: dict[str, Any]
    code_identity: dict[str, Any]
    decisions: list[AuditDecision]
    reclassification_ids: list[int]

    @property
    def digest(self) -> str:
        return snapshot_digest(self.model_dump(mode="json"))


def code_identity() -> dict[str, Any]:
    # Include working source hashes: the base commit alone cannot identify an
    # uncommitted, reviewed extractor/guard. A later source change needs a new audit.
    paths = sorted((ROOT / "src").glob("*.py")) + [ROOT / "scripts/refresh_metadata.py"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RefreshRejected("Cannot identify code baseline")
    return {"base_commit": commit,
            "working_source_sha256": {p.relative_to(ROOT).as_posix(): sha256_file(p) for p in paths}}


def observation(plan: RefreshPlan) -> dict[str, Any]:
    """Bind all old/new metadata, not just candidate IDs or classification fields."""
    plan.require_applicable()
    papers = sorted(plan.papers, key=lambda p: p.paper_id)
    if (len(papers) != plan.expected_count or len(plan.pdf_manifest) != plan.expected_count
            or len({p.paper_id for p in papers}) != plan.expected_count
            or len({p.file_hash for p in papers}) != plan.expected_count):
        raise RefreshRejected("Incomplete or duplicate manifest inventory")
    return {
        "corpus_size": plan.expected_count,
        "database_stamp": plan.database_stamp.model_dump(),
        "database_snapshot_sha256": plan.database_snapshot_sha256,
        "pdf_manifest": {k: v.model_dump() for k, v in sorted(plan.pdf_manifest.items())},
        "db_paper_ids": [p.paper_id for p in papers],
        "metadata_changed_ids": [p.paper_id for p in papers if p.changes],
        "classification_input_changed_ids": [p.paper_id for p in papers if p.input_changed],
        "bibliographic_only_ids": [p.paper_id for p in papers if p.changes and not p.input_changed],
        "paper_deltas": [{"paper_id": p.paper_id, "filename": p.filename, "file_hash": p.file_hash,
                          "old_metadata_sha256": snapshot_digest(p.old_metadata),
                          "new_metadata_sha256": snapshot_digest(p.new_metadata.model_dump(mode="json")),
                          "input_field_changes": {key: key in p.changes for key in INPUT_FIELDS}}
                         for p in papers],
        "audit_evidence": plan.audit_evidence,
    }


def _format_input(metadata: dict[str, Any]) -> dict[str, Any]:
    def spaces(value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None
    abstract = metadata["abstract"]
    # This narrow exception covers an orphan Abstract-heading period. It never
    # removes words, boilerplate paragraphs, footnotes, keyword concepts or case.
    if abstract and abstract.startswith(". "):
        abstract = abstract[2:]
    return {"title": spaces(metadata["title"]), "abstract": spaces(abstract),
            "introduction_excerpt": spaces(metadata["introduction_excerpt"]),
            "keywords": [spaces(term) for item in metadata["keywords"]
                         for term in item.split("·")]}


def format_equivalent(paper: RefreshPaper) -> bool:
    return _format_input(paper.old_metadata) == _format_input(paper.new_metadata.model_dump())


def _validate_decisions(plan: RefreshPlan, decisions: list[AuditDecision]) -> list[int]:
    ids = [d.paper_id for d in decisions]
    if len(ids) != len(set(ids)) or sorted(ids) != sorted(plan.target_ids):
        raise RefreshRejected("Audit decisions must cover exactly the input candidate set")
    by_id = {p.paper_id: p for p in plan.papers}
    for decision in decisions:
        if decision.verdict == "C":
            raise RefreshRejected("Questionable metadata must be resolved before freezing")
        if decision.verdict == "B" and not format_equivalent(by_id[decision.paper_id]):
            raise RefreshRejected("Format-only exception changes substantive input")
    return sorted(d.paper_id for d in decisions if d.verdict == "A")


def freeze_manifest(plan: RefreshPlan, decisions: list[AuditDecision]) -> RefreshManifest:
    """Called only after PDF-based review, never automatically by the CLI."""
    return RefreshManifest(generated_at=datetime.now(timezone.utc).isoformat(),
                           observation=observation(plan), code_identity=code_identity(),
                           decisions=sorted(decisions, key=lambda d: d.paper_id),
                           reclassification_ids=_validate_decisions(plan, decisions))


def validate_manifest(plan: RefreshPlan, manifest: RefreshManifest) -> None:
    if (observation(plan) != manifest.observation or code_identity() != manifest.code_identity
            or _validate_decisions(plan, manifest.decisions) != manifest.reclassification_ids):
        raise RefreshRejected("Frozen manifest differs from current observation or code")


def bind_manifest(plan: RefreshPlan, manifest: RefreshManifest) -> None:
    validate_manifest(plan, manifest)
    plan.expected_input_ids = list(manifest.observation["classification_input_changed_ids"])
    plan.format_only_ids = sorted(d.paper_id for d in manifest.decisions if d.verdict == "B")
    plan.frozen_manifest_sha256 = manifest.digest


def check_binding(plan: RefreshPlan, manifest: RefreshManifest | None) -> None:
    if manifest is None:
        if plan.frozen_manifest_sha256 or plan.format_only_ids:
            raise RefreshRejected("Frozen manifest is required for the reviewed plan")
        return  # Generic synthetic/library callers retain the strict all-diffs behavior.
    validate_manifest(plan, manifest)
    expected = plan.model_copy(deep=True)
    bind_manifest(expected, manifest)
    if expected.digest != plan.digest:
        raise RefreshRejected("Plan is not bound to the frozen manifest")


def load_manifest(path: Path, expected_sha256: str | None) -> RefreshManifest:
    manifest = RefreshManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if expected_sha256 is not None and manifest.digest != expected_sha256:
        raise RefreshRejected("Manifest does not match the reviewed digest")
    return manifest
