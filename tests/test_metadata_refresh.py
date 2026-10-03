"""Controlled refresh tests use only tmp_path databases and synthetic PDFs."""

import json
from pathlib import Path
import shutil
import sqlite3

import pymupdf
import pytest

from src.classifier import ClassificationError
from src.database import Database, snapshot_digest
from src.metadata_refresh import (
    PHASE_A_IDS, RefreshPlan, RefreshRejected, _metadata_protected,
    apply_metadata, build_plan, dry_run_report, file_stamp, inventory,
    read_baseline, reclassify_targets, summary,
)
from src.models import ClassificationResult, ExtractedMetadata
from src.pdf_parser import parse_pdf, sha256_file


ABSTRACT = "We evaluate authentication protocols through controlled experiments and report security findings. " * 3


def answer(category="Authentication"):
    return ClassificationResult(
        primary_category=category, tags=["AI label"], research_methods=["Experimental Study"],
        target_vulnerabilities=["AI vulnerability"], relevance="B",
        relevance_reason="Synthetic authentication experiments.", relevance_confidence=0.8,
    )


def pdf(path, number):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 50), f"Synthetic Authentication Study {number}", fontsize=20)
        page.insert_text((50, 100), "Abstract", fontsize=12)
        page.insert_textbox((50, 125, 550, 450), ABSTRACT, fontsize=10)
        doc.save(path)


class FakeClassifier:
    provider = "local"
    model = "synthetic-model"

    def __init__(self):
        self.calls = []

    def classify(self, **kwargs):
        self.calls.append(kwargs)
        return answer("Authorization")

    def close(self):
        pass


@pytest.fixture
def library(tmp_path, database, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    new = {}
    for n in range(1, 4):
        path = inbox / f"paper-{n}.pdf"
        pdf(path, n)
        metadata = ExtractedMetadata(
            title=f"Synthetic Authentication Study {n}", abstract=ABSTRACT,
            authors=["New Author"], year=2025, venue="Synthetic Security Conference",
            keywords=["Authentication"], metadata_sources={"title": "first page layout"},
        )
        new[path.name] = metadata
        old = metadata.model_copy(deep=True)
        if n == 1:
            old.title = "Previous Authentication Study"
        if n == 2:
            old.authors = ["Previous Author"]
            old.year = 2024
            old.venue = "Previous Conference"
        paper_id = database.add_paper(
            file_hash=sha256_file(path), filename=path.name, filepath=str(path), metadata=old,
            classification=answer(), classification_provider="local", classification_model="original-model",
            processing_seconds=12.5,
        )
        # Both reviewed and unreviewed current values must be preserved verbatim.
        database.update_review(
            paper_id, primary_category="Session Management", relevance="A", status="Important",
            relevance_reason="Human reasoning", tags=["Human tag"],
            research_methods=["Human method"], target_vulnerabilities=["Human vulnerability"],
        )
        with database.connect() as con:
            con.execute("UPDATE papers SET manually_reviewed = ?, relevance_confidence = ?, classification_error = ? WHERE id = ?",
                        (n % 2, 0.91, "Previous diagnostic", paper_id))
    monkeypatch.setattr("src.metadata_refresh.extract_metadata", lambda parsed, filename: new[filename])
    return database, inbox, new, tmp_path / "backups"


def plan_for(library, **kwargs):
    db, inbox, _, _ = library
    return build_plan(db, inbox, expected_count=3, **kwargs)[0]


def apply_for(library, plan=None):
    db, inbox, _, backups = library
    plan = plan or plan_for(library)
    return plan, apply_metadata(db, inbox, plan, backup_dir=backups)


def test_metadata_only_preserves_every_ai_human_status_and_history_value(library):
    db, inbox, new, backups = library
    stamp, before = read_baseline(db)
    plan, receipt = apply_for(library)
    _, after = read_baseline(db)
    assert _metadata_protected(before) == _metadata_protected(after)
    assert [db.get_paper(n)["title"] for n in range(1, 4)] == [new[f"paper-{n}.pdf"].title for n in range(1, 4)]
    assert receipt.target_ids == [1]
    assert receipt.database_snapshot_sha256 == snapshot_digest(after)
    backup = backups / receipt.backup_filename
    assert sha256_file(backup) == stamp.sha256
    assert read_baseline(Database(backup))[1] == before
    assert inventory(inbox)[0] == plan.pdf_manifest


@pytest.mark.parametrize("status", ["classified", "pending", "failed", "needs_review"])
def test_metadata_refresh_preserves_classification_status(library, status):
    db = library[0]
    with db.connect() as con:
        con.execute("UPDATE papers SET classification_status = ? WHERE id = 1", (status,))
    apply_for(library)
    assert db.get_paper(1)["classification_status"] == status


def test_dry_run_zero_writes_and_no_initialize(library, monkeypatch):
    db, inbox, _, backups = library
    stamp, before = read_baseline(db)
    monkeypatch.setattr(db, "initialize", lambda: pytest.fail("Must never initialize"))
    monkeypatch.setattr(db, "connect", lambda: pytest.fail("Must not use writable connection"))
    plan, baseline = build_plan(db, inbox, expected_count=3)
    assert file_stamp(db.path) == stamp
    assert read_baseline(db)[1] == before
    assert not backups.exists()
    assert not list(db.path.parent.glob("papers.db-*"))
    assert baseline["classification_runs_count"] == 3
    assert baseline["manually_reviewed_count"] == 2
    assert baseline["paper_labels"]["1"]["current_tags"] == ["Human tag"]
    assert baseline["paper_labels"]["1"]["ai_methods"] == ["Experimental Study"]
    assert "filepath" not in baseline["tables"]["papers"][0]
    for table in ("paper_tags", "paper_methods", "paper_vulnerabilities", "classification_runs"):
        assert baseline["tables"][table] == before["tables"][table]
    report = dry_run_report(plan)
    assert str(inbox) not in report and ABSTRACT not in report
    assert summary(plan)["metadata_changed"] == 2
    assert summary(plan)["bibliographic_only_changed"] == 1
    assert summary(plan)["target_ids"] == [1]


def test_readonly_connection_enforces_no_writes(library):
    db = library[0]
    before = file_stamp(db.path)
    with db.connect_readonly() as con, pytest.raises(sqlite3.OperationalError):
        con.execute("UPDATE papers SET title = 'write'")
    assert file_stamp(db.path) == before


def test_controlled_write_connection_cannot_create_missing_db(tmp_path):
    db = Database(tmp_path / "missing/papers.db")
    with pytest.raises(ValueError, match="already exist"), db.connect(existing_only=True):
        pytest.fail("No new database may be created")
    assert not db.path.exists() and not db.path.parent.exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_active_sidecars_rejected(library, suffix):
    db = library[0]
    Path(str(db.path) + suffix).write_bytes(b"synthetic sidecar")
    with pytest.raises(ValueError, match="sidecars"):
        plan_for(library)


@pytest.mark.parametrize("fault", ["hash", "missing", "unexpected", "duplicate", "invalid"])
def test_identity_faults_reject_apply_without_backup_or_db_write(library, fault):
    db, inbox, _, backups = library
    path = inbox / "paper-1.pdf"
    if fault == "hash":
        with path.open("ab") as f:
            f.write(b"changed")
    elif fault == "missing":
        path.unlink()
    elif fault == "unexpected":
        pdf(inbox / "unexpected.pdf", 99)
    elif fault == "duplicate":
        shutil.copyfile(path, inbox / "duplicate.pdf")
    else:
        (inbox / "invalid.PDF").write_bytes(b"not a PDF")
    before = file_stamp(db.path)
    plan = plan_for(library)
    assert plan.errors
    with pytest.raises(RefreshRejected):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert file_stamp(db.path) == before and not backups.exists()


def test_duplicate_db_hash_rejected(library):
    db = library[0]
    with sqlite3.connect(db.path) as con:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("CREATE TABLE unconstrained AS SELECT * FROM papers")
        con.execute("DROP TABLE papers")
        con.execute("ALTER TABLE unconstrained RENAME TO papers")
        con.execute("INSERT INTO papers SELECT * FROM papers WHERE id = 1")
    plan = plan_for(library)
    assert "Duplicate database hash" in plan.errors


def test_filename_is_not_identity(library):
    db, inbox, new, _ = library
    (inbox / "paper-1.pdf").rename(inbox / "renamed.pdf")
    new["renamed.pdf"] = new["paper-1.pdf"]
    plan = plan_for(library)
    assert not plan.errors and len(plan.papers) == 3
    assert plan.papers[0].filename == "paper-1.pdf"
    apply_for(library, plan)
    assert db.get_paper(1)["filename"] == "paper-1.pdf"


@pytest.mark.parametrize("field", ["title", "abstract", "keywords", "introduction_excerpt"])
def test_classification_input_change_detection(library, field):
    db = library[0]
    column = "keywords_json" if field == "keywords" else field
    value = json.dumps(["Previous keyword"]) if field == "keywords" else "Previous input"
    with db.connect() as con:
        # Column selected solely from the parametrized internal constant list.
        con.execute(f"UPDATE papers SET {column} = ? WHERE id = 3", (value,))
    plan = plan_for(library)
    assert plan.target_ids == [1, 3]


def test_phase_b_bibliographic_change_is_not_reclassified(library):
    plan = plan_for(library)
    paper = plan.papers[1]
    assert set(paper.changes) == {"authors", "year", "venue"}
    assert not paper.input_changed and 2 not in plan.target_ids


@pytest.mark.parametrize("fault", ["title", "abstract", "review_reason"])
def test_input_issues_reject_apply_preserving_existing_state(library, fault):
    db, inbox, new, backups = library
    if fault == "title":
        new["paper-1.pdf"].title = "bad"
    elif fault == "abstract":
        new["paper-1.pdf"].abstract = "too short"
    else:
        new["paper-1.pdf"].review_reasons = ["Synthetic extractor hold"]
    before = file_stamp(db.path)
    plan = plan_for(library)
    assert summary(plan)["classification_input_issues"] == 1
    with pytest.raises(RefreshRejected):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert file_stamp(db.path) == before and not backups.exists()
    assert db.get_paper(1)["classification_status"] == "classified"


def test_expected_targets_gate_mismatch(library):
    plan = plan_for(library, expected_input_ids=[1, 2])
    assert not summary(plan)["apply_allowed"]


def test_extraction_failure_diagnostic_is_sanitized(library, monkeypatch):
    def fail(*args):
        raise RuntimeError("secret path and full paper text")
    monkeypatch.setattr("src.metadata_refresh.parse_pdf", fail)
    plan = plan_for(library)
    assert len(plan.errors) == 3 and not plan.papers
    assert "secret" not in dry_run_report(plan)


def test_stale_plan_db_change_rejected(library):
    db, inbox, _, backups = library
    plan = plan_for(library)
    with db.connect() as con:
        con.execute("UPDATE papers SET status = 'Read' WHERE id = 3")
    before = file_stamp(db.path)
    with pytest.raises(RefreshRejected, match="stale"):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert file_stamp(db.path) == before and not backups.exists()


def test_altered_plan_new_metadata_rejected(library):
    db, inbox, _, backups = library
    plan = plan_for(library)
    plan.papers[0].new_metadata = plan.papers[0].new_metadata.model_copy(update={"year": 2030})
    before = file_stamp(db.path)
    with pytest.raises(RefreshRejected, match="stale"):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert file_stamp(db.path) == before


def test_extractor_invalid_value_rejected_before_backup(library):
    db, inbox, new, backups = library
    new["paper-1.pdf"].year = 2200
    plan = plan_for(library)
    assert any("ValidationError" in error for error in plan.errors)
    before = file_stamp(db.path)
    with pytest.raises(RefreshRejected):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert file_stamp(db.path) == before and not backups.exists()


def test_pdf_change_during_preflight_rejected(library, monkeypatch):
    _, inbox, new, _ = library
    mutated = []
    def mutate(parsed, filename):
        if not mutated:
            mutated.append(True)
            (inbox / "new-invalid.pdf").write_bytes(b"not a PDF")
        return new[filename]
    monkeypatch.setattr("src.metadata_refresh.extract_metadata", mutate)
    plan = plan_for(library)
    assert "Database or PDF inventory changed during preflight" in plan.errors


def test_apply_transaction_rolls_back_all_papers(library, monkeypatch):
    db, inbox, _, backups = library
    plan = plan_for(library)
    stamp, before = read_baseline(db)
    original = db.update_metadata_only
    calls = []
    def fail_second(*args):
        calls.append(args[1])
        if len(calls) == 2:
            raise RuntimeError("synthetic write failure")
        original(*args)
    monkeypatch.setattr(db, "update_metadata_only", fail_second)
    with pytest.raises(RuntimeError):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert calls == [1, 2]
    assert read_baseline(db)[1] == before
    assert sha256_file(next(backups.iterdir())) == stamp.sha256


def test_apply_trigger_cannot_change_protected_values(library):
    db, inbox, _, backups = library
    with db.connect() as con:
        con.execute("CREATE TRIGGER unsafe AFTER UPDATE OF title ON papers BEGIN UPDATE papers SET status = 'Read' WHERE id = new.id; END")
    plan = plan_for(library)
    before = read_baseline(db)[1]
    with pytest.raises(RefreshRejected, match="protected"):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert read_baseline(db)[1] == before


def test_pdf_added_during_write_rolls_back(library, monkeypatch):
    db, inbox, _, backups = library
    plan = plan_for(library)
    before = read_baseline(db)[1]
    original = db.update_metadata_only
    def mutate(*args):
        original(*args)
        (inbox / "late-invalid.pdf").write_bytes(b"not a PDF")
    monkeypatch.setattr(db, "update_metadata_only", mutate)
    with pytest.raises(RefreshRejected, match="PDF inventory"):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert read_baseline(db)[1] == before


def test_backup_is_unique_and_never_overwritten(library):
    db, inbox, _, backups = library
    _, first = apply_for(library)
    old = file_stamp(backups / first.backup_filename)
    plan = plan_for(library)
    second = apply_metadata(db, inbox, plan, backup_dir=backups)
    assert first.backup_filename != second.backup_filename
    assert file_stamp(backups / first.backup_filename) == old


def test_backup_collision_prevents_writes(library, monkeypatch):
    db, inbox, _, backups = library
    plan = plan_for(library)
    backups.mkdir()
    (backups / "collision.db.bak").write_bytes(b"existing backup")
    monkeypatch.setattr("src.metadata_refresh.unique_name", lambda *_: "collision.db.bak")
    before = read_baseline(db)[1]
    with pytest.raises(FileExistsError):
        apply_metadata(db, inbox, plan, backup_dir=backups)
    assert read_baseline(db)[1] == before
    assert (backups / "collision.db.bak").read_bytes() == b"existing backup"


def test_backup_inside_inbox_rejected(library):
    db, inbox, _, _ = library
    plan = plan_for(library)
    before = read_baseline(db)[1]
    with pytest.raises(RefreshRejected, match="outside"):
        apply_metadata(db, inbox, plan, backup_dir=inbox / "backups")
    assert read_baseline(db)[1] == before


def test_targeted_retry_only_calls_changed_paper_preserves_humans_and_history(library):
    db, inbox, _, backups = library
    plan, receipt = apply_for(library)
    before = read_baseline(db)[1]
    fake = FakeClassifier()
    result = reclassify_targets(db, inbox, plan, receipt, classifier=fake, backup_dir=backups)
    after = read_baseline(db)[1]
    assert len(fake.calls) == 1 and fake.calls[0]["title"] == plan.papers[0].new_metadata.title
    assert result["target_ids"] == [1] and result["classified"] == 1
    assert after["tables"]["papers"][1:] == before["tables"]["papers"][1:]
    history = db.classification_history(1)
    assert len(history) == 2 and history[0]["model"] == "original-model"
    assert history[0]["result"] == answer().model_dump(mode="json")
    assert history[1]["provider"] == "local" and history[1]["model"] == "synthetic-model"
    assert history[1]["classified_at"].endswith("Z")
    paper = db.get_paper(1)
    assert paper["primary_category"] == "Session Management" and paper["manually_reviewed"]
    assert paper["status"] == "Important" and paper["relevance_confidence"] == 0.91
    assert paper["tags"] == ["Human tag"] and paper["research_methods"] == ["Human method"]
    assert paper["target_vulnerabilities"] == ["Human vulnerability"]
    assert paper["ai_primary_category"] == "Authorization"
    assert fake.calls[0]["introduction_excerpt"] is None


def test_targeted_retry_preserves_unreviewed_current_values(library):
    db, inbox, _, backups = library
    with db.connect() as con:
        con.execute("UPDATE papers SET manually_reviewed = 0 WHERE id = 1")
    plan, receipt = apply_for(library)
    reclassify_targets(db, inbox, plan, receipt, classifier=FakeClassifier(), backup_dir=backups)
    paper = db.get_paper(1)
    assert not paper["manually_reviewed"] and paper["primary_category"] == "Session Management"
    assert paper["tags"] == ["Human tag"] and paper["status"] == "Important"


def test_targeted_failure_preserves_previous_ai_and_appends_sanitized_history(library):
    db, inbox, _, backups = library
    plan, receipt = apply_for(library)
    before = db.get_paper(1)
    class Failing(FakeClassifier):
        def classify(self, **kwargs):
            raise ClassificationError("private payload")
    result = reclassify_targets(db, inbox, plan, receipt, classifier=Failing(), backup_dir=backups)
    assert result["failed"] == 1 and result["classified"] == 0
    after = db.get_paper(1)
    for key in ("ai_primary_category", "ai_tags", "classification_provider", "classification_model", "classified_at", "status"):
        assert before[key] == after[key]
    runs = db.classification_history(1)
    assert len(runs) == 2 and runs[-1]["status"] == "failed"
    assert "private" not in runs[-1]["error"]


@pytest.mark.parametrize("fault", ["receipt", "state", "pdf", "backup", "replay", "forged_old"])
def test_targeted_retry_rejects_changed_evidence_before_provider(library, fault):
    db, inbox, _, backups = library
    plan, receipt = apply_for(library)
    if fault == "receipt":
        receipt = receipt.model_copy(update={"target_ids": [1, 2]})
    elif fault == "state":
        db.update_review(2, primary_category="Authorization", tags=[], relevance="A", status="Read")
    elif fault == "pdf":
        with (inbox / "paper-1.pdf").open("ab") as f:
            f.write(b"changed")
    elif fault == "backup":
        (backups / receipt.backup_filename).write_bytes(b"corrupt")
    elif fault == "replay":
        reclassify_targets(db, inbox, plan, receipt, classifier=FakeClassifier(), backup_dir=backups)
    else:
        plan.papers[1].old_metadata["title"] = "Invented previous input"
        receipt = receipt.model_copy(update={"plan_sha256": plan.digest, "target_ids": plan.target_ids})
    fake = FakeClassifier()
    before = file_stamp(db.path)
    with pytest.raises((RefreshRejected, sqlite3.DatabaseError)):
        reclassify_targets(db, inbox, plan, receipt, classifier=fake, backup_dir=backups)
    assert not fake.calls and file_stamp(db.path) == before


def test_targeted_retry_concurrent_review_rejects_results(library):
    db, inbox, _, backups = library
    plan, receipt = apply_for(library)
    class Concurrent(FakeClassifier):
        def classify(self, **kwargs):
            db.update_review(2, primary_category="Authorization", tags=[], relevance="A", status="Read")
            return answer()
    with pytest.raises(RefreshRejected, match="state changed"):
        reclassify_targets(db, inbox, plan, receipt, classifier=Concurrent(), backup_dir=backups)
    assert len(db.classification_history(1)) == 1 and db.get_paper(2)["status"] == "Read"


def test_targeted_batch_write_rollback(library, monkeypatch):
    db, inbox, _, backups = library
    with db.connect() as con:
        con.execute("UPDATE papers SET title = 'Older Study of Authentication' WHERE id = 2")
    plan, receipt = apply_for(library)
    assert plan.target_ids == [1, 2]
    before = read_baseline(db)[1]
    original = db.write_classification
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise RuntimeError("synthetic classification write failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(db, "write_classification", fail_second)
    with pytest.raises(RuntimeError):
        reclassify_targets(db, inbox, plan, receipt, classifier=FakeClassifier(), backup_dir=backups)
    assert calls == [1, 2] and read_baseline(db)[1] == before


def test_targeted_intro_used_only_when_abstract_missing(library):
    db, inbox, new, backups = library
    new["paper-1.pdf"].abstract = None
    new["paper-1.pdf"].introduction_excerpt = ABSTRACT
    plan, receipt = apply_for(library)
    fake = FakeClassifier()
    reclassify_targets(db, inbox, plan, receipt, classifier=fake, backup_dir=backups)
    assert fake.calls[0]["abstract"] is None and fake.calls[0]["introduction_excerpt"] == ABSTRACT.strip()


def test_bibliographic_only_library_makes_no_provider_calls(library):
    db, inbox, new, backups = library
    with db.connect() as con:
        con.execute("UPDATE papers SET title = ? WHERE id = 1", (new["paper-1.pdf"].title,))
    plan, receipt = apply_for(library)
    assert plan.target_ids == []
    before = file_stamp(db.path)
    fake = FakeClassifier()
    result = reclassify_targets(db, inbox, plan, receipt, classifier=fake, backup_dir=backups)
    assert not fake.calls and result["target_ids"] == [] and file_stamp(db.path) == before


def test_targeted_retry_trigger_cannot_overwrite_human_data(library):
    db, inbox, _, backups = library
    with db.connect() as con:
        con.execute("CREATE TRIGGER unsafe_ai AFTER UPDATE OF ai_primary_category ON papers BEGIN UPDATE papers SET status = 'Read' WHERE id = new.id; END")
    plan, receipt = apply_for(library)
    before = read_baseline(db)[1]
    with pytest.raises(RefreshRejected, match="protected"):
        reclassify_targets(db, inbox, plan, receipt, classifier=FakeClassifier(), backup_dir=backups)
    assert read_baseline(db)[1] == before


def test_plan_json_roundtrip(library):
    plan = plan_for(library)
    loaded = RefreshPlan.model_validate_json(plan.model_dump_json())
    assert loaded.digest == plan.digest


def test_real_parser_and_extractor_metadata_apply(tmp_path, database):
    from src.metadata_extractor import extract_metadata
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "real.pdf"
    pdf(path, 7)
    new = extract_metadata(parse_pdf(path, inbox), path.name)
    assert not new.review_reasons
    old = new.model_copy(update={"authors": ["Previous Author"]})
    database.add_paper(file_hash=sha256_file(path), filename=path.name, filepath=str(path),
                       metadata=old, classification=answer())
    plan, _ = build_plan(database, inbox, expected_count=1)
    plan.require_applicable()
    assert not plan.target_ids
    apply_metadata(database, inbox, plan, backup_dir=tmp_path / "backups")
    assert database.get_paper(1)["authors"] == new.authors


@pytest.fixture
def phase_evidence(tmp_path, database, monkeypatch):
    inbox = tmp_path / "phase-inbox"
    audit = tmp_path / "audit"
    inbox.mkdir()
    audit.mkdir()
    current, a, b, protected = {}, [], [], {}
    for n in range(1, 41):
        path = inbox / f"phase-{n}.pdf"
        pdf(path, n)
        old = ExtractedMetadata(title=f"Synthetic Authentication Study {n}", abstract=ABSTRACT)
        phase_a = old.model_copy(deep=True)
        if n in PHASE_A_IDS:
            phase_a.title = f"Updated Authentication Study {n}"
        phase_b = phase_a.model_copy(update={"authors": ["Phase B Author"], "year": 2025})
        current[path.name] = phase_b
        h = sha256_file(path)
        database.add_paper(file_hash=h, filename=path.name, filepath=str(path), metadata=old, classification=answer())
        a.append({"id": n, "filename": path.name, "old": old.model_dump(), "new": phase_a.model_dump()})
        b.append({"id": n, "filename": path.name, "old": phase_a.model_dump(), "new": phase_b.model_dump()})
        protected[f"papers/inbox/{path.name}"] = {"sha256": h}
    for name, value in (("phase-a-final.json", a), ("phase-b-final.json", b), ("phase-a-protected.json", protected)):
        (audit / name).write_text(json.dumps(value), encoding="utf-8")
    (audit / "phase-a-report.md").write_text("\n".join(f"### ID {n} — fixture" for n in PHASE_A_IDS), encoding="utf-8")
    monkeypatch.setattr("src.metadata_refresh.extract_metadata", lambda parsed, filename: current[filename])
    return database, inbox, audit


def test_phase_a_targets_and_phase_b_160_fields_verified(phase_evidence):
    db, inbox, audit = phase_evidence
    plan, _ = build_plan(db, inbox, expected_input_ids=list(PHASE_A_IDS), audit_dir=audit)
    assert not plan.errors and plan.target_ids == list(PHASE_A_IDS)
    assert plan.audit_evidence["phase_b_input_fields_equal"] == 160
    assert summary(plan)["bibliographic_only_changed"] == 28


def test_phase_a_incidental_changes_block_expected_twelve_but_verify_phase_b(phase_evidence):
    import src.metadata_refresh as refresh
    db, inbox, audit = phase_evidence
    a = json.loads((audit / "phase-a-final.json").read_text())
    b = json.loads((audit / "phase-b-final.json").read_text())
    extras = [9, 20, 25, 28, 33]
    for n in extras:
        metadata = refresh.extract_metadata(None, f"phase-{n}.pdf")
        metadata.title = f"Incidental Authentication Study {n}"
        a[n - 1]["new"]["title"] = metadata.title
        b[n - 1]["old"]["title"] = metadata.title
        b[n - 1]["new"]["title"] = metadata.title
    (audit / "phase-a-final.json").write_text(json.dumps(a), encoding="utf-8")
    (audit / "phase-b-final.json").write_text(json.dumps(b), encoding="utf-8")
    plan, _ = build_plan(db, inbox, expected_input_ids=list(PHASE_A_IDS), audit_dir=audit)
    assert len(plan.target_ids) == 17
    assert plan.audit_evidence["phase_b_input_fields_equal"] == 160
    assert plan.audit_evidence["phase_a_additional_input_changed_ids"] == extras
    assert plan.errors == ["Classification input target set differs from expected IDs"]
    with pytest.raises(RefreshRejected):
        plan.require_applicable()


@pytest.mark.parametrize("fault", ["phase_b_input", "old_input", "hash", "filename", "report_ids", "missing", "duplicate"])
def test_phase_evidence_mismatch_rejects_apply(phase_evidence, fault):
    db, inbox, audit = phase_evidence
    if fault == "report_ids":
        (audit / "phase-a-report.md").write_text("### ID 1", encoding="utf-8")
    elif fault == "missing":
        (audit / "phase-b-final.json").unlink()
    else:
        name = "phase-a-protected.json" if fault == "hash" else "phase-b-final.json" if fault == "phase_b_input" else "phase-a-final.json"
        value = json.loads((audit / name).read_text())
        if fault == "hash":
            value["papers/inbox/phase-1.pdf"]["sha256"] = "a" * 64
        elif fault == "filename":
            value[0]["filename"] = "wrong.pdf"
        elif fault == "duplicate":
            value.append(value[0])
        else:
            value[0]["new" if fault == "phase_b_input" else "old"]["title"] = "Different input"
        (audit / name).write_text(json.dumps(value), encoding="utf-8")
    plan, _ = build_plan(db, inbox, expected_input_ids=list(PHASE_A_IDS), audit_dir=audit)
    with pytest.raises(RefreshRejected):
        plan.require_applicable()


def test_cli_requires_explicit_mode_plan_and_provider():
    from scripts.refresh_metadata import main
    for args in ([], ["--apply"], ["--reclassify", "--plan", "synthetic.json"]):
        with pytest.raises(SystemExit):
            main(args)


def test_cli_dry_run_does_not_load_provider_or_settings(library, tmp_path, monkeypatch, capsys):
    import scripts.refresh_metadata as cli
    plan = plan_for(library)
    _, baseline = build_plan(library[0], library[1], expected_count=3)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "build_plan", lambda *args, **kwargs: (plan, baseline))
    monkeypatch.setattr("src.classifier.create_classifier", lambda *_: pytest.fail("No provider"))
    monkeypatch.setattr("src.config.get_settings", lambda *_: pytest.fail("No settings"))
    before = file_stamp(library[0].path)
    output = tmp_path / "data/metadata-refresh"
    assert cli.main(["--dry-run", "--database", str(library[0].path), "--inbox", str(library[1]),
                     "--output-dir", str(output), "--backup-dir", str(tmp_path / "data/backups")]) == 0
    assert len(list(output.iterdir())) == 3 and file_stamp(library[0].path) == before
    assert str(tmp_path) not in capsys.readouterr().out


def test_cli_refuses_evidence_path_inside_inbox(library, monkeypatch, tmp_path):
    import scripts.refresh_metadata as cli
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    assert cli.main(["--dry-run", "--database", str(library[0].path), "--inbox", str(library[1]),
                     "--output-dir", str(library[1] / "reports")]) == 2
    assert not (library[1] / "reports").exists()
