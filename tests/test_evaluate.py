from scripts.evaluate import evaluate_rows


def test_evaluation_calculates_accuracy_and_f1() -> None:
    rows = [
        {"ground_truth_category": "Authentication", "ai_primary_category": "Authentication"},
        {"ground_truth_category": "Authentication", "ai_primary_category": "Authorization"},
        {"ground_truth_category": "Authorization", "ai_primary_category": "Authorization"},
    ]
    result = evaluate_rows(rows)
    assert result["evaluated"] == 3
    assert result["accuracy"] == 2 / 3
    assert result["per_category"]["Authorization"]["precision"] == 0.5
