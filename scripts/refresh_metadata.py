"""Explicit dry-run / metadata apply / targeted reclassification CLI.

Run from the project root: python -m scripts.refresh_metadata --dry-run
Private artifacts are written exclusively under the ignored data directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.database import Database
from src.metadata_refresh import (
    ApplyReceipt, RefreshPlan, apply_metadata, build_plan,
    dry_run_report, reclassify_targets, summary, unique_name, verify_phase_evidence,
)
from src.refresh_manifest import bind_manifest, check_binding, load_manifest


ROOT = Path(__file__).resolve().parents[1]


def write_private(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value)


def private_directory(path: Path, inbox: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to((ROOT / "data").resolve()) or resolved.is_relative_to(inbox.resolve()):
        raise ValueError("Evidence and backups must stay under project data, outside the inbox")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--reclassify", action="store_true")
    parser.add_argument("--database", type=Path, default=ROOT / "data/papers.db")
    parser.add_argument("--inbox", type=Path, default=ROOT / "papers/inbox")
    parser.add_argument("--audit-dir", type=Path, default=ROOT / "data/metadata-audit-40")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/metadata-refresh")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "data/backups")
    parser.add_argument("--plan", type=Path, help="Reviewed local dry-run plan; required for writes")
    parser.add_argument("--manifest", type=Path, help="PDF-audited frozen manifest; required for writes")
    parser.add_argument("--manifest-sha256", help="Reviewed canonical manifest digest; required for writes")
    parser.add_argument("--receipt", type=Path, help="Metadata apply receipt; required for reclassification")
    parser.add_argument("--provider", choices=("local", "openai"), help="Explicit provider for reclassification")
    args = parser.parse_args(argv)
    if (args.apply or args.reclassify) and not args.plan:
        parser.error("--plan is required for writes")
    if (args.apply or args.reclassify) and (not args.manifest or not args.manifest_sha256):
        parser.error("--manifest and --manifest-sha256 are required for writes")
    if args.reclassify and (not args.receipt or not args.provider):
        parser.error("--receipt and --provider are required for reclassification")
    try:
        database = Database(args.database)
        if database.path.is_relative_to(args.inbox.resolve()):
            raise ValueError("Database must be outside the immutable inbox")
        output = private_directory(args.output_dir, args.inbox)
        backups = private_directory(args.backup_dir, args.inbox)
        if args.manifest_sha256 and not args.manifest:
            raise ValueError("Digest requires a manifest")
        manifest = load_manifest(args.manifest, args.manifest_sha256) if args.manifest else None
        if args.dry_run:
            plan, baseline = build_plan(database, args.inbox, expected_count=40,
                                        audit_dir=args.audit_dir)
            if manifest is not None:
                bind_manifest(plan, manifest)
            output.mkdir(parents=True, exist_ok=True)
            prefix = unique_name("dry-run", "")
            write_private(output / (prefix + "-baseline.json"), json.dumps(baseline, ensure_ascii=False, indent=2))
            write_private(output / (prefix + "-plan.json"), plan.model_dump_json(indent=2))
            write_private(output / (prefix + "-report.md"), dry_run_report(plan))
            print(json.dumps(summary(plan), ensure_ascii=False, indent=2))
            print("Local evidence prefix: " + prefix)
            return 0 if summary(plan)["apply_allowed"] else 2
        plan = RefreshPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
        if plan.expected_count != 40:
            raise ValueError("Plan must match the controlled 40-paper workflow")
        check_binding(plan, manifest)
        plan_digest = plan.digest
        verify_phase_evidence(plan, args.audit_dir)
        plan.require_applicable()
        if plan.digest != plan_digest:
            raise ValueError("Audit evidence differs from the reviewed dry-run")
        output.mkdir(parents=True, exist_ok=True)
        if args.apply:
            receipt = apply_metadata(database, args.inbox, plan, backup_dir=backups,
                                     audit_dir=args.audit_dir, manifest=manifest)
            filename = unique_name("metadata-apply", "-receipt.json")
            write_private(output / filename, receipt.model_dump_json(indent=2))
            print("Metadata apply completed. Local receipt: " + filename)
        else:
            # No settings, secrets, provider clients or logs are loaded in dry-run/apply.
            from dataclasses import replace
            from src.classifier import create_classifier
            from src.config import get_settings

            receipt = ApplyReceipt.model_validate_json(args.receipt.read_text(encoding="utf-8"))
            settings = replace(get_settings(), classifier_provider=args.provider)
            classifier = create_classifier(settings)
            try:
                result = reclassify_targets(database, args.inbox, plan, receipt,
                                            classifier=classifier, backup_dir=backups, manifest=manifest)
            finally:
                classifier.close()
            write_private(output / unique_name("targeted-reclassification", ".json"),
                          json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # Underlying paths, validation payloads, paper text and secrets stay private.
        print(f"Controlled refresh rejected ({type(exc).__name__}); no automatic fallback")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
