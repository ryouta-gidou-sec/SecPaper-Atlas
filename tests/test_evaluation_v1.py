from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.evaluation_v1 import (
    PRIMARY_CLASSES, RELEVANCE_CLASSES, PROTOCOL, content_digest, evaluate_frozen,
    multilabel_metrics, normalize_labels, single_label_metrics,
)


def test_primary_perfect_fixed_macro_and_absent_support() -> None:
    result = single_label_metrics([PRIMARY_CLASSES[0]] * 2, [PRIMARY_CLASSES[0]] * 2, PRIMARY_CLASSES)
    assert result["accuracy"] == result["micro_f1"] == 1
    assert result["macro_f1"] == result["macro_precision"] == result["macro_recall"] == 1 / 8
    assert result["per_class"][PRIMARY_CLASSES[1]]["support"] == 0
    assert result["per_class"][PRIMARY_CLASSES[1]]["f1"] == 0


def test_primary_all_mismatch() -> None:
    result = single_label_metrics([PRIMARY_CLASSES[0]], [PRIMARY_CLASSES[1]], PRIMARY_CLASSES)
    assert result["accuracy"] == result["macro_f1"] == result["micro_f1"] == 0
    assert result["confusion_matrix"][0][1] == 1


def test_all_eight_classes_perfect() -> None:
    result = single_label_metrics(list(PRIMARY_CLASSES), list(PRIMARY_CLASSES), PRIMARY_CLASSES)
    assert result["macro_f1"] == 1


def test_relevance_three_class_confusion() -> None:
    result = single_label_metrics(["A", "B", "B", "C"], ["B", "B", "A", "C"], RELEVANCE_CLASSES)
    assert result["confusion_matrix"] == [[0, 1, 0], [1, 1, 0], [0, 0, 1]]
    assert result["accuracy"] == 0.5
    assert result["macro_f1"] == 0.5


def test_multilabel_exact_micro_macro_and_union() -> None:
    result = multilabel_metrics([["a", "b"], ["a"], []], [["a", "c"], ["a"], []], "tags")
    assert result["exact_match_accuracy"] == 2 / 3
    assert result["micro_precision"] == result["micro_recall"] == result["micro_f1"] == 2 / 3
    assert result["macro_precision"] == result["macro_recall"] == result["macro_f1"] == 1 / 3
    assert result["per_label"]["c"]["support"] == 0
    assert result["per_label"]["b"]["fn"] == 1


@pytest.mark.parametrize("truth,predicted,exact,fp,fn", [([], [], 1, 0, 0), ([], ["x"], 0, 1, 0), (["x"], [], 0, 0, 1)])
def test_empty_sets(truth: list[str], predicted: list[str], exact: int, fp: int, fn: int) -> None:
    result = multilabel_metrics([truth], [predicted], "tags")
    assert result["exact_match_accuracy"] == exact
    assert result["micro_f1"] == result["macro_f1"] == 0
    assert result["fp"] == fp and result["fn"] == fn


def test_normalization_dictionary_field_scope_and_duplicates() -> None:
    assert normalize_labels(["  Cross-Site  Request Forgery (CSRF) ", "csrf", "SQLi",
                             "Black Box Testing", "Black-box Testing"], "tags") == ["Black-box Testing", "CSRF", "SQL Injection"]
    assert normalize_labels(["SQLi", " Black  box testing "], "research_methods") == ["Black-box Testing", "SQLi"]
    assert normalize_labels(["Black Box Testing", "sqli"], "target_vulnerabilities") == ["Black Box Testing", "SQL Injection"]
    assert normalize_labels(["Foo", "foo", "Login CSRF", "IDOR", "BOLA", "Machine Learning", "Reinforcement Learning"], "tags") == ["BOLA", "Foo", "IDOR", "Login CSRF", "Machine Learning", "Reinforcement Learning", "foo"]
    assert multilabel_metrics([["CSRF"]], [["csrf", "CSRF"]], "tags")["micro_f1"] == 1


@pytest.mark.parametrize("invalid", [None, "[]", [""], [" "], [1]])
def test_missing_invalid_multilabel_rejected(invalid: object) -> None:
    with pytest.raises(ValueError):
        normalize_labels(invalid, "tags")


@pytest.mark.parametrize("truth,predicted", [([], []), (["A"], []), (["a"], ["A"]), (["Unknown"], ["A"])])
def test_invalid_single_labels(truth: list[str], predicted: list[str]) -> None:
    with pytest.raises(ValueError):
        single_label_metrics(truth, predicted, RELEVANCE_CLASSES)


@pytest.fixture
def locked_artifacts(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    papers = [{"paper_id": pid, "file_hash": f"{pid:064x}", "ai_prediction": {
        "ai_primary_category": PRIMARY_CLASSES[0], "ai_relevance": "A", "ai_tags": [],
        "ai_research_methods": [], "ai_target_vulnerabilities": []}} for pid in range(1, 41)]
    frozen = {"dataset_identifier": "evaluation-dataset-v1", "papers": papers}
    shared = {"dataset_identifier": "evaluation-dataset-v1", "dataset_content_digest": content_digest(frozen)}
    gt = {**shared, "human_final_approval": True, "rubric_version": "v1", "normalization_version": "normalization-v1", "papers": [
        {"paper_id": p["paper_id"], "file_hash": p["file_hash"],
         "role": "development" if p["paper_id"] <= 8 else "heldout",
         "primary_category": PRIMARY_CLASSES[1] if p["paper_id"] <= 8 else PRIMARY_CLASSES[0],
         "relevance": "B" if p["paper_id"] <= 8 else "A", "tags": ["dev"] if p["paper_id"] <= 8 else [],
         "research_methods": [], "target_vulnerabilities": []} for p in papers]}
    split = {**shared, "split_version": "split-v1", "development_ids": list(range(1, 9)),
             "heldout_ids": list(range(9, 41)), "papers": [{k: p[k] for k in ("paper_id", "file_hash", "role")} for p in gt["papers"]]}
    values = [{"content": frozen, "dataset_identifier": "evaluation-dataset-v1", "freeze_status": "frozen", "dataset_content_digest": content_digest(frozen)},
              *[{"content": v, "content_digest": content_digest(v)} for v in (gt, split, PROTOCOL)]]
    paths = tuple(tmp_path / f"{i}.json" for i in range(4))
    for path, value in zip(paths, values):
        path.write_text(json.dumps(value), encoding="utf-8")
    return paths


def test_heldout_exact_ids_development_excluded_and_deterministic(locked_artifacts: tuple[Path, ...]) -> None:
    before = [p.read_bytes() for p in locked_artifacts]
    result = evaluate_frozen(*locked_artifacts)
    assert result == evaluate_frozen(*locked_artifacts)
    assert result["paper_ids"] == list(range(9, 41)) and result["evaluated"] == 32
    assert result["fields"]["primary_category"]["accuracy"] == 1
    assert result["fields"]["relevance"]["accuracy"] == 1
    assert result["fields"]["tags"]["exact_match_accuracy"] == 1
    assert [p.read_bytes() for p in locked_artifacts] == before


@pytest.mark.parametrize("change", ["digest", "split", "hash", "duplicate", "role", "approval", "normalization", "protocol", "dataset"])
def test_corrupt_locks_rejected(locked_artifacts: tuple[Path, ...], change: str) -> None:
    index = 2 if change == "split" else 3 if change == "protocol" else 1
    path = locked_artifacts[index]
    value = json.loads(path.read_text())
    c = value["content"]
    if change == "digest": value["content_digest"] = "0" * 64
    elif change == "split": c["heldout_ids"] = list(range(8, 40))
    elif change == "hash": c["papers"][8]["file_hash"] = "f" * 64
    elif change == "duplicate": c["papers"][8]["paper_id"] = 10
    elif change == "role": c["papers"][8]["role"] = "development"
    elif change == "approval": c["human_final_approval"] = False
    elif change == "normalization": c["normalization_version"] = "new"
    elif change == "protocol": c["zero_division"] = 1
    elif change == "dataset": c["dataset_content_digest"] = "0" * 64
    if change != "digest": value["content_digest"] = content_digest(c)
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError): evaluate_frozen(*locked_artifacts)


def test_frozen_cli_direct_and_module(locked_artifacts: tuple[Path, ...]) -> None:
    args = [argument for name, path in zip(("--frozen-manifest", "--ground-truth", "--split", "--protocol"), locked_artifacts) for argument in (name, str(path))]
    for entry in (["scripts/evaluate.py"], ["-m", "scripts.evaluate"]):
        run = subprocess.run([sys.executable, *entry, *args], capture_output=True, text=True, check=True)
        assert json.loads(run.stdout)["evaluated"] == 32
    run = subprocess.run([sys.executable, "scripts/evaluate.py", "--split", str(locked_artifacts[2])], capture_output=True)
    assert run.returncode != 0
