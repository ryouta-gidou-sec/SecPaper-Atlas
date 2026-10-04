"""Offline, read-only evaluation of explicitly locked frozen artifacts."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

PRIMARY_CLASSES = (
    "Authentication", "Session Management", "Authorization", "Token Security",
    "OAuth / OIDC / SSO", "Account Management", "Vulnerability Assessment", "Other Security",
)
RELEVANCE_CLASSES = ("A", "B", "C")
MULTILABEL_FIELDS = ("tags", "research_methods", "target_vulnerabilities")
NORMALIZATION_VERSION = "normalization-v1"
PROTOCOL = {
    "version": "evaluation-protocol-v1",
    "dataset_identifier": "evaluation-dataset-v1",
    "development_ids": list(range(1, 9)),
    "heldout_ids": list(range(9, 41)),
    "heldout_n": 32,
    "primary_classes": list(PRIMARY_CLASSES),
    "relevance_classes": list(RELEVANCE_CLASSES),
    "single_label_metrics": ["accuracy", "micro_precision", "micro_recall", "micro_f1",
                             "macro_precision", "macro_recall", "macro_f1", "per_class",
                             "confusion_matrix"],
    "confusion_orientation": "rows ground truth; columns prediction",
    "single_label_macro": "fixed class order, including absent classes",
    "multilabel_fields": list(MULTILABEL_FIELDS),
    "multilabel_metrics": ["exact_match_accuracy", "micro_precision", "micro_recall",
                           "micro_f1", "macro_precision", "macro_recall", "macro_f1",
                           "per_label"],
    "multilabel_macro": "sorted GT/prediction label union across heldout cohort",
    "zero_division": 0,
    "empty_union_macro": 0,
    "empty_sets_exact_match": True,
    "missing_or_invalid_values": "error; never silently excluded",
    "normalization_version": NORMALIZATION_VERSION,
    "rubric_version": "v1",
    "prediction_selection": "freeze manifest current AI prediction only; no history selection",
    "no_posthoc_tuning": "One-shot frozen evaluation. Do not use IDs 9-40 to change prompt, "
                         "model, normalization, taxonomy, GT or regenerate predictions. "
                         "Future improvements require development data and an independent test set.",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_labels(values: Any, field: str) -> list[str]:
    """Apply only rubric v1 whitespace, field-specific dictionary and exact deduplication."""
    if field not in MULTILABEL_FIELDS:
        raise ValueError(f"Unknown multi-label field: {field}")
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"{field} requires an explicit list of nonempty strings (missing is invalid)")
    aliases: dict[str, str] = {}
    if field in ("tags", "target_vulnerabilities"):
        aliases.update({v: "CSRF" for v in (
            "csrf", "cross site request forgery", "cross-site request forgery",
            "cross site request forgery (csrf)", "cross-site request forgery (csrf)")})
        aliases.update({"sqli": "SQL Injection", "sql injection": "SQL Injection"})
    if field in ("tags", "research_methods"):
        aliases.update({"black box testing": "Black-box Testing",
                        "black-box testing": "Black-box Testing"})
    cleaned = [" ".join(value.split()) for value in values]
    return sorted({aliases.get(value.casefold(), value) for value in cleaned})


def _ratios(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "support": tp + fn,
            "predicted": tp + fp, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def _averages(per_label: dict[str, Any]) -> dict[str, float | int]:
    micro = _ratios(*(sum(v[k] for v in per_label.values()) for k in ("tp", "fp", "fn")))
    result = {k: micro[k] for k in ("tp", "fp", "fn")}
    for metric in ("precision", "recall", "f1"):
        result["micro_" + metric] = micro[metric]
        result["macro_" + metric] = (
            sum(v[metric] for v in per_label.values()) / len(per_label) if per_label else 0.0
        )
    return result


def single_label_metrics(truth: list[str], predicted: list[str], classes: tuple[str, ...]) -> dict[str, Any]:
    if not truth or len(truth) != len(predicted):
        raise ValueError("Single-label inputs must have equal, nonzero lengths")
    if any(not isinstance(v, str) or v.strip() not in classes for v in truth + predicted):
        raise ValueError("Invalid single-label value")
    truth, predicted = [v.strip() for v in truth], [v.strip() for v in predicted]
    pairs = Counter(zip(truth, predicted))
    matrix = [[pairs[a, b] for b in classes] for a in classes]
    per_class = {}
    for i, label in enumerate(classes):
        tp = matrix[i][i]
        per_class[label] = _ratios(tp, sum(row[i] for row in matrix) - tp, sum(matrix[i]) - tp)
    return {"evaluated": len(truth), "accuracy": sum(a == b for a, b in zip(truth, predicted)) / len(truth),
            "classes": list(classes), "confusion_matrix": matrix, "per_class": per_class,
            **_averages(per_class)}


def multilabel_metrics(truth: list[list[str]], predicted: list[list[str]], field: str) -> dict[str, Any]:
    if not truth or len(truth) != len(predicted):
        raise ValueError("Multi-label inputs must have equal, nonzero lengths")
    expected = [set(normalize_labels(v, field)) for v in truth]
    actual = [set(normalize_labels(v, field)) for v in predicted]
    labels = sorted(set().union(*expected, *actual))
    per_label = {}
    for label in labels:
        tp = sum(label in a and label in b for a, b in zip(expected, actual))
        fp = sum(label not in a and label in b for a, b in zip(expected, actual))
        fn = sum(label in a and label not in b for a, b in zip(expected, actual))
        per_label[label] = _ratios(tp, fp, fn)
    return {"evaluated": len(truth),
            "exact_match_accuracy": sum(a == b for a, b in zip(expected, actual)) / len(truth),
            "labels": labels, "per_label": per_label, **_averages(per_label)}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return value


def _locked(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("content_digest") != content_digest(value.get("content")):
        raise ValueError("Locked artifact content digest mismatch")
    return value["content"]


def _index(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed = {}
    hashes = set()
    for record in records:
        pid, file_hash = record.get("paper_id"), record.get("file_hash")
        if type(pid) is not int or pid in indexed:
            raise ValueError("Invalid or duplicate paper ID")
        if (not isinstance(file_hash, str) or len(file_hash) != 64
                or any(c not in "0123456789abcdef" for c in file_hash) or file_hash in hashes):
            raise ValueError("Invalid or duplicate file hash")
        hashes.add(file_hash)
        indexed[pid] = record
    if set(indexed) != set(range(1, 41)):
        raise ValueError("Artifacts must contain exactly IDs 1-40")
    return indexed


def evaluate_frozen(manifest_path: Path, ground_truth_path: Path, split_path: Path,
                    protocol_path: Path) -> dict[str, Any]:
    """Validate locks, join by ID and hash, evaluate exactly heldout 9-40; never access DB."""
    manifest = _read(manifest_path)
    frozen = manifest["content"]
    dataset_digest = content_digest(frozen)
    if (manifest.get("freeze_status") != "frozen"
            or manifest.get("dataset_identifier") != "evaluation-dataset-v1"
            or manifest.get("dataset_content_digest") != dataset_digest
            or frozen.get("dataset_identifier") != "evaluation-dataset-v1"):
        raise ValueError("Invalid frozen dataset identity")
    gt_artifact, split_artifact = _read(ground_truth_path), _read(split_path)
    gt, split = _locked(gt_artifact), _locked(split_artifact)
    protocol = _locked(_read(protocol_path))
    if protocol != PROTOCOL:
        raise ValueError("Protocol differs from evaluation-protocol-v1")
    for artifact in (gt, split):
        if (artifact.get("dataset_content_digest") != dataset_digest
                or artifact.get("dataset_identifier") != "evaluation-dataset-v1"):
            raise ValueError("GT/split dataset identity mismatch")
    if (gt.get("rubric_version") != "v1" or gt.get("normalization_version") != NORMALIZATION_VERSION
            or gt.get("human_final_approval") is not True):
        raise ValueError("Ground truth must be approved with rubric v1 / normalization-v1")
    if (split.get("split_version") != "split-v1"
            or split.get("development_ids") != list(range(1, 9))
            or split.get("heldout_ids") != list(range(9, 41))):
        raise ValueError("Split must lock development 1-8 and heldout exactly 9-40")
    predicted, expected, roles = (_index(v["papers"]) for v in (frozen, gt, split))
    for pid in range(1, 41):
        if not (predicted[pid]["file_hash"] == expected[pid]["file_hash"] == roles[pid]["file_hash"]):
            raise ValueError("Paper hash mismatch across frozen/GT/split artifacts")
        role = "development" if pid <= 8 else "heldout"
        if expected[pid].get("role") != role or roles[pid].get("role") != role:
            raise ValueError("Invalid split role")
    ids = split["heldout_ids"]
    fields = {}
    for field, classes in (("primary_category", PRIMARY_CLASSES), ("relevance", RELEVANCE_CLASSES)):
        fields[field] = single_label_metrics(
            [expected[pid][field] for pid in ids],
            [predicted[pid]["ai_prediction"]["ai_" + field] for pid in ids], classes)
    for field in MULTILABEL_FIELDS:
        fields[field] = multilabel_metrics(
            [expected[pid][field] for pid in ids],
            [predicted[pid]["ai_prediction"]["ai_" + field] for pid in ids], field)
    return {"evaluated": len(ids), "paper_ids": ids, "dataset_content_digest": dataset_digest,
            "ground_truth_digest": gt_artifact["content_digest"],
            "split_digest": split_artifact["content_digest"], "protocol_digest": content_digest(protocol),
            "normalization_version": NORMALIZATION_VERSION, "rubric_version": "v1", "fields": fields}
