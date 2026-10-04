"""Compare human category labels with AI predictions from CSV or provider history."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any


def evaluate_rows(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Calculate accuracy and per-category precision, recall, and F1."""

    usable = [
        row
        for row in rows
        if row.get("ground_truth_category", "").strip()
        and row.get("ai_primary_category", "").strip()
    ]
    if not usable:
        return {"evaluated": 0, "accuracy": None, "per_category": {}}

    truth = [row["ground_truth_category"].strip() for row in usable]
    predicted = [row["ai_primary_category"].strip() for row in usable]
    correct = sum(expected == actual for expected, actual in zip(truth, predicted))
    categories = sorted(set(truth) | set(predicted))
    metrics: dict[str, dict[str, float | int]] = {}
    for category in categories:
        true_positive = sum(
            expected == category and actual == category
            for expected, actual in zip(truth, predicted)
        )
        false_positive = sum(
            expected != category and actual == category
            for expected, actual in zip(truth, predicted)
        )
        false_negative = sum(
            expected == category and actual != category
            for expected, actual in zip(truth, predicted)
        )
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[category] = {
            "support": Counter(truth)[category],
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return {
        "evaluated": len(usable),
        "accuracy": correct / len(usable),
        "per_category": metrics,
    }


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def evaluate_provider_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Compare each provider/model to the same human labels, one latest run per hash."""
    groups: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for row in rows:
        key = (row.get("provider") or "unknown", row.get("model") or "unknown")
        groups.setdefault(key, {})[row["file_hash"]] = row
    return {key: evaluate_rows(list(papers.values())) for key, papers in groups.items()}


def load_database_rows(path: Path) -> list[dict[str, str]]:
    """Read successful run history and explicitly reviewed current labels, read-only."""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        records = connection.execute(
            """SELECT p.file_hash, p.primary_category AS ground_truth_category,
                      r.provider, r.model, r.result_json
               FROM classification_runs r JOIN papers p ON p.id = r.paper_id
               WHERE p.manually_reviewed = 1 AND r.status = 'classified'
               ORDER BY r.id"""
        ).fetchall()
    return [
        {"file_hash": row["file_hash"], "ground_truth_category": row["ground_truth_category"],
         "provider": row["provider"], "model": row["model"],
         "ai_primary_category": json.loads(row["result_json"]).get("primary_category", "")}
        for row in records if row["result_json"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=Path("data/ground_truth.csv"),
    )
    parser.add_argument("--database", type=Path, help="Compare saved provider/model runs to Human Review labels")
    parser.add_argument("--frozen-manifest", type=Path, help="Evaluate locked frozen five-field artifacts")
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--protocol", type=Path)
    args = parser.parse_args()
    frozen_paths = (args.frozen_manifest, args.ground_truth, args.split, args.protocol)
    if any(frozen_paths):
        if not all(frozen_paths) or args.database or args.csv_path != Path("data/ground_truth.csv"):
            parser.error("Frozen evaluation requires all four artifact paths and no CSV/database input")
        try:
            # Supports both direct script execution and python -m scripts.evaluate.
            if __package__:
                from .evaluation_v1 import evaluate_frozen
            else:
                from evaluation_v1 import evaluate_frozen
            result = evaluate_frozen(*frozen_paths)
        except (ValueError, KeyError, TypeError, OSError) as error:
            parser.error(str(error))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return
    if args.database:
        groups = evaluate_provider_rows(load_database_rows(args.database))
        if not groups:
            print("No reviewed successful classification runs to evaluate.")
        for (provider, model), result in groups.items():
            print(f"Provider: {provider}; model: {model}")
            print_metrics(result)
        return
    result = evaluate_rows(load_rows(args.csv_path))
    print_metrics(result)


def print_metrics(result: dict[str, Any]) -> None:
    if not result["evaluated"]:
        print("No fully labeled rows to evaluate.")
        return
    print(f"Evaluated: {result['evaluated']}")
    print(f"Category accuracy: {result['accuracy']:.3f}")
    print("Per-category metrics:")
    for category, values in result["per_category"].items():
        print(
            f"- {category}: precision={values['precision']:.3f}, "
            f"recall={values['recall']:.3f}, f1={values['f1']:.3f}, "
            f"support={values['support']}"
        )


if __name__ == "__main__":
    main()
