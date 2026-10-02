from scripts.evaluate import evaluate_rows
from scripts.evaluate import evaluate_provider_rows, load_database_rows
from src.models import ClassificationResult, ExtractedMetadata


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


def test_provider_evaluation_uses_latest_success_per_hash_and_separate_groups():
    common = {"file_hash": "a" * 64, "ground_truth_category": "Authentication"}
    rows = [
        {**common, "provider": "local", "model": "small", "ai_primary_category": "Authorization"},
        {**common, "provider": "local", "model": "small", "ai_primary_category": "Authentication"},
        {**common, "provider": "openai", "model": "api", "ai_primary_category": "Authorization"},
    ]
    metrics = evaluate_provider_rows(rows)
    assert metrics[("local", "small")]["evaluated"] == 1
    assert metrics[("local", "small")]["accuracy"] == 1
    assert metrics[("openai", "api")]["accuracy"] == 0


def test_database_evaluation_excludes_unreviewed_and_failed_runs(database):
    classification = ClassificationResult(
        primary_category="Authentication", tags=[], research_methods=[], target_vulnerabilities=[],
        relevance="B", relevance_reason="Authentication study.", relevance_confidence=0.8,
    )
    paper_id = database.add_paper(
        file_hash="a" * 64, filename="fixture.pdf", filepath="fixture.pdf",
        metadata=ExtractedMetadata(title="An Authentication Paper"), classification=classification,
        classification_provider="local", classification_model="local-model",
    )
    assert load_database_rows(database.path) == []
    database.update_review(paper_id, primary_category="Authentication", tags=[], relevance="B", status="Read")
    database.update_classification(paper_id, None, classification_status="failed", classification_provider="openai", classification_model="api-model")
    rows = load_database_rows(database.path)
    assert len(rows) == 1
    assert rows[0]["provider"] == "local"
    assert evaluate_provider_rows(rows)[("local", "local-model")]["accuracy"] == 1
