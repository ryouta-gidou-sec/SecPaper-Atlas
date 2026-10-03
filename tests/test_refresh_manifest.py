"""Frozen observation guards; production data/providers are never used."""

import json

import pytest

from test_metadata_refresh import (
    ABSTRACT, FakeClassifier, library, phase_evidence, plan_for,
)
from src.metadata_refresh import (
    RefreshRejected, apply_metadata, build_plan, file_stamp, read_baseline,
    reclassify_targets,
)
from src.refresh_manifest import (
    AuditDecision, RefreshManifest, bind_manifest, check_binding, freeze_manifest,
    load_manifest, validate_manifest,
)


def decisions(plan, format_ids=()):
    return [AuditDecision(paper_id=n, verdict="B" if n in format_ids else "A",
                          phase_a_scope="secondary", reason="Reviewed synthetic PDF delta",
                          source_page=1, source_evidence="Synthetic article page inspected")
            for n in plan.target_ids]


def test_frozen_roundtrip_and_full_observation(library):
    plan = plan_for(library)
    manifest = freeze_manifest(plan, decisions(plan))
    assert manifest.observation["metadata_changed_ids"] == [1, 2]
    assert manifest.observation["classification_input_changed_ids"] == [1]
    assert manifest.observation["bibliographic_only_ids"] == [2]
    loaded = RefreshManifest.model_validate_json(manifest.model_dump_json())
    assert loaded.digest == manifest.digest
    bind_manifest(plan, loaded)
    check_binding(plan, loaded)
    assert plan.expected_input_ids == [1] and plan.reclassification_ids == [1]


@pytest.mark.parametrize("fault", ["new_value_same_ids", "old_value_same_ids", "bibliography", "extra", "missing",
                                 "pdf", "baseline", "code", "duplicate", "reclassification", "audit"])
def test_manifest_mismatch_rejects_before_backup_and_write(library, fault):
    db, inbox, _, backups = library
    plan = plan_for(library)
    manifest = freeze_manifest(plan, decisions(plan))
    bind_manifest(plan, manifest)
    if fault == "new_value_same_ids":
        plan.papers[0].new_metadata.title = "Another Authentication Study"
    elif fault == "old_value_same_ids":
        plan.papers[0].old_metadata["title"] = "Invented old title"
    elif fault == "bibliography":
        plan.papers[1].new_metadata.year = 2023
    elif fault == "extra":
        plan.papers[2].new_metadata.title = "Extra Authentication Study"
    elif fault == "missing":
        plan.papers[0].new_metadata.title = plan.papers[0].old_metadata["title"]
    elif fault == "pdf":
        plan.pdf_manifest["paper-1.pdf"].sha256 = "a" * 64
    elif fault == "baseline":
        plan.database_stamp.mtime_ns += 1
    elif fault == "code":
        manifest.code_identity["base_commit"] = "a" * 40
    elif fault == "duplicate":
        plan.papers[2] = plan.papers[0]
    elif fault == "reclassification":
        manifest.reclassification_ids.append(3)
    else:
        plan.audit_evidence["unexpected"] = True
    before = file_stamp(db.path)
    with pytest.raises(RefreshRejected):
        apply_metadata(db, inbox, plan, backup_dir=backups, manifest=manifest)
    assert file_stamp(db.path) == before and not backups.exists()


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate", "questionable", "false_format"])
def test_audit_candidate_decisions_cannot_silently_expand_or_shrink(library, fault):
    plan = plan_for(library)
    reviewed = decisions(plan)
    if fault == "missing":
        reviewed.clear()
    elif fault == "extra":
        reviewed.append(reviewed[0].model_copy(update={"paper_id": 3}))
    elif fault == "duplicate":
        reviewed.append(reviewed[0])
    else:
        reviewed[0].verdict = "C" if fault == "questionable" else "B"
    with pytest.raises(RefreshRejected):
        freeze_manifest(plan, reviewed)


@pytest.mark.parametrize("format_kind", ["period", "keywords", "whitespace", "both"])
def test_format_only_candidates_apply_metadata_without_reclassifying(library, format_kind):
    db, inbox, _, backups = library
    with db.connect() as con:
        if format_kind in ("period", "both"):
            con.execute("UPDATE papers SET abstract = ? WHERE id = 3", (". " + ABSTRACT.strip(),))
        if format_kind in ("keywords", "both"):
            con.execute("UPDATE papers SET keywords_json = ? WHERE id = 3",
                        (json.dumps(["Authentication · Protocols"]),))
            library[2]["paper-3.pdf"].keywords = ["Authentication", "Protocols"]
        if format_kind == "whitespace":
            con.execute("UPDATE papers SET abstract = ? WHERE id = 3", (ABSTRACT.strip().replace(" ", "  "),))
    plan = plan_for(library)
    assert plan.target_ids == [1, 3]
    manifest = freeze_manifest(plan, decisions(plan, [3]))
    bind_manifest(plan, manifest)
    assert plan.format_only_ids == [3] and plan.reclassification_ids == [1]
    receipt = apply_metadata(db, inbox, plan, backup_dir=backups, manifest=manifest)
    before = read_baseline(db)[1]
    fake = FakeClassifier()
    result = reclassify_targets(db, inbox, plan, receipt, classifier=fake,
                               backup_dir=backups, manifest=manifest)
    assert result["target_ids"] == [1] and len(fake.calls) == 1
    after = read_baseline(db)[1]
    assert before["tables"]["papers"][2] == after["tables"]["papers"][2]
    assert len(db.classification_history(3)) == 1
    assert len(db.classification_history(1)) == 2


@pytest.mark.parametrize("removed", [" Content Warning: source paragraph.", " ACM classification: Security.",
                                     " Corresponding author", " New scientific result."])
def test_removing_words_is_never_a_format_only_exception(library, removed):
    with library[0].connect() as con:
        con.execute("UPDATE papers SET abstract = ? WHERE id = 3", (ABSTRACT.strip() + removed,))
    plan = plan_for(library)
    with pytest.raises(RefreshRejected, match="substantive"):
        freeze_manifest(plan, decisions(plan, [3]))


@pytest.mark.parametrize("bound", [False, True])
def test_missing_manifest_cannot_authorize_format_exclusions(library, bound):
    plan = plan_for(library)
    if bound:
        bind_manifest(plan, freeze_manifest(plan, decisions(plan)))
    else:
        plan.format_only_ids = [1]
    before = file_stamp(library[0].path)
    with pytest.raises(RefreshRejected, match="required"):
        apply_metadata(library[0], library[1], plan, backup_dir=library[3])
    assert file_stamp(library[0].path) == before and not library[3].exists()


def test_manifest_fresh_reparse_detects_changed_value_even_with_same_ids(library):
    plan = plan_for(library)
    manifest = freeze_manifest(plan, decisions(plan))
    bind_manifest(plan, manifest)
    library[2]["paper-1.pdf"].title = "Later Authentication Study"
    before = file_stamp(library[0].path)
    with pytest.raises(RefreshRejected):
        apply_metadata(library[0], library[1], plan, backup_dir=library[3], manifest=manifest)
    assert file_stamp(library[0].path) == before and not library[3].exists()


def test_secondary_phase_a_candidates_are_derived_and_frozen(phase_evidence):
    db, inbox, audit = phase_evidence
    import src.metadata_refresh as refresh
    a = json.loads((audit / "phase-a-final.json").read_text())
    b = json.loads((audit / "phase-b-final.json").read_text())
    extras = [9, 20, 25, 28, 33]
    for n in extras:
        latest = refresh.extract_metadata(None, f"phase-{n}.pdf")
        latest.title = f"Secondary Authentication Study {n}"
        a[n - 1]["new"]["title"] = latest.title
        b[n - 1]["old"]["title"] = b[n - 1]["new"]["title"] = latest.title
    (audit / "phase-a-final.json").write_text(json.dumps(a), encoding="utf-8")
    (audit / "phase-b-final.json").write_text(json.dumps(b), encoding="utf-8")
    plan, _ = build_plan(db, inbox, audit_dir=audit)
    assert not plan.errors and len(plan.target_ids) == 17
    assert plan.audit_evidence["phase_a_additional_input_changed_ids"] == extras
    manifest = freeze_manifest(plan, decisions(plan))
    bind_manifest(plan, manifest)
    assert len(plan.expected_input_ids) == 17
    validate_manifest(plan, manifest)


def test_manifest_digest_pin_rejects_altered_artifact(library, tmp_path):
    plan = plan_for(library)
    manifest = freeze_manifest(plan, decisions(plan))
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    assert load_manifest(path, manifest.digest).digest == manifest.digest
    manifest.decisions[0].reason = "Changed after review"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    with pytest.raises(RefreshRejected, match="reviewed digest"):
        load_manifest(path, "a" * 64)


def test_cli_manifest_dry_run_is_readonly(library, tmp_path, monkeypatch):
    import scripts.refresh_metadata as cli
    plan, baseline = build_plan(library[0], library[1], expected_count=3)
    manifest = freeze_manifest(plan, decisions(plan))
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "build_plan", lambda *a, **kw: (plan, baseline))
    monkeypatch.setattr("src.classifier.create_classifier", lambda *a: pytest.fail("No provider"))
    monkeypatch.setattr("src.config.get_settings", lambda *a: pytest.fail("No settings"))
    monkeypatch.setattr(library[0], "connect", lambda *a, **kw: pytest.fail("No writable connection"))
    before = file_stamp(library[0].path)
    output = tmp_path / "data/metadata-refresh"
    assert cli.main(["--dry-run", "--database", str(library[0].path), "--inbox", str(library[1]),
                     "--output-dir", str(output), "--backup-dir", str(tmp_path / "data/backups"),
                     "--manifest", str(path), "--manifest-sha256", manifest.digest]) == 0
    assert file_stamp(library[0].path) == before
    saved = json.loads(next(output.glob("*-plan.json")).read_text())
    assert saved["frozen_manifest_sha256"] == manifest.digest
    assert not (tmp_path / "data/backups").exists()


@pytest.mark.parametrize("mode", ["--apply", "--reclassify"])
def test_cli_writes_require_manifest_and_independent_digest_pin(mode):
    from scripts.refresh_metadata import main
    with pytest.raises(SystemExit):
        main([mode, "--plan", "unbound.json"])


def test_cli_wrong_manifest_pin_stops_before_database_access(library, tmp_path, monkeypatch):
    import scripts.refresh_metadata as cli
    manifest = freeze_manifest(plan_for(library), decisions(plan_for(library)))
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "build_plan", lambda *a, **kw: pytest.fail("Must reject pin first"))
    assert cli.main(["--dry-run", "--database", str(library[0].path), "--inbox", str(library[1]),
                     "--output-dir", str(tmp_path / "data/out"), "--backup-dir", str(tmp_path / "data/backups"),
                     "--manifest", str(path), "--manifest-sha256", "a" * 64]) == 2
    assert not (tmp_path / "data/out").exists()
