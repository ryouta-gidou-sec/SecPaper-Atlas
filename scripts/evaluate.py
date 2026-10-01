"""Compute simple category metrics from a human-reviewed ground-truth CSV."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from pathlib import Path
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=Path("data/ground_truth.csv"),
    )
    args = parser.parse_args()
    result = evaluate_rows(load_rows(args.csv_path))
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
